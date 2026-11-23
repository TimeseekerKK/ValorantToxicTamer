import sys
import logging

from PySide6.QtCore import QLockFile, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon, QWidget

from .config_manager import ConfigManager, data_directory, set_autostart, validate_config
from .diagnostics import configure_logging
from .hotkey import Hotkeys
from .message_manager import MessageManager
from .sender import Sender
from .tray import Tray
from .win32_api import WindowsAPI
from .wheel_settings import WheelSettings
from .app_version import VERSION


class Notifications(QObject):
    message = Signal(str)


class Application(QObject):
    def __init__(self, app, directory):
        super().__init__()
        self.app = app
        self.config = ConfigManager(directory / "config.json")
        self.messages = MessageManager(directory / "messages.json")
        self.messages.set_mode(self.config.value["category_mode"])
        self.log_handler = configure_logging(directory)
        self.api = WindowsAPI()
        self.notifications = Notifications()
        self.sender = Sender(self.messages, self.api, self.config.value["cooldown"],
                             self.notifications.message.emit)
        self.window = None
        self.quitting = False
        self.wheel_settings = WheelSettings(directory / "category-wheel.json")
        self.wheel = None
        self.quit_timer = QTimer(self)
        self.quit_timer.setInterval(25)
        self.quit_timer.timeout.connect(self._finish_quit)
        self.last_message = None
        # Keep the native hotkey handle alive independently of the optional UI.
        self.hotkey_window = QWidget()
        self.hotkeys = Hotkeys(app, int(self.hotkey_window.winId()), self.api, self.trigger)
        if self.wheel_settings.enabled:
            try:
                self.wheel = self._create_wheel()
            except OSError as exc:
                self.wheel_settings.error = f"类别轮盘未启动：{exc}"
                logging.getLogger("ValorantToxicTamer").warning("%s", self.wheel_settings.error)
        self.tray = Tray(self.reveal, self.quit, self, font_size=self.config.value["font_size"])
        self.notifications.message.connect(self.report)
        app.aboutToQuit.connect(self.cleanup)
        registered = self.hotkeys.configure(self.config.value)
        if not self.config.value["start_hidden"] or not registered:
            self.reveal(0 if registered else 1)
        self.tray.showMessage("ValorantToxicTamer", "已启动。双击托盘图标管理消息。" if registered
                              else "快捷键注册失败，请在设置中选择其他按键。")
        if getattr(self.log_handler, "startup_error", None):
            self.report("诊断日志不可用，程序仍可正常使用：" + self.log_handler.startup_error)

    @Slot(str)
    def report(self, message):
        if self.quitting:
            return
        logging.getLogger("ValorantToxicTamer").info("status: %s", message)
        self.last_message = message
        visible = self.window is not None and self.window.isVisible()
        if visible:
            self.window.report(message)
        if not visible and not message.startswith(("已忽略", "队伍输入", "全体输入")):
            self.tray.showMessage("ValorantToxicTamer", message, QSystemTrayIcon.MessageIcon.Warning)

    def reveal(self, page=0):
        if self.quitting:
            return
        if self.window is None:
            from .ui import MainWindow
            self.window = MainWindow(self.messages, self.config, self.sender, self.save_settings,
                                     wheel_settings=self.wheel_settings, save_wheel_settings=self.save_wheel_settings)
            self.window.updater.ready_to_install.connect(self.quit)
        self.window.set_hotkey_status(self.hotkeys.status)
        self.window.reveal(page)
        if self.last_message is not None:
            self.window.report(self.last_message)

    def trigger(self, channel):
        if self.quitting or (self.wheel is not None and self.wheel.visible):
            return False
        triggered = self.sender.trigger(channel)
        if self.window is not None and self.window.isVisible():
            self.window.refresh_status()
        return triggered

    def _wheel_can_open(self):
        with self.sender.lock:
            return (not self.quitting and not self.sender.busy
                    and not self.sender.cancel.is_set() and QApplication.activeModalWidget() is None
                    and (self.window is None or self.window.management.import_worker is None))

    def _create_wheel(self):
        from .category_wheel import CategoryWheel
        return CategoryWheel(self.app, int(self.hotkey_window.winId()), self.api, self.sender,
                             self.wheel_settings, self._wheel_can_open, self._select_wheel_categories, self.report)

    def _select_wheel_categories(self, categories):
        try:
            self.sender.select_wheel_categories(categories)
        except ValueError as exc:
            self.report(f"已忽略：{exc}")
        else:
            if self.window is not None and self.window.isVisible():
                self.window.refresh_status()

    def _close_wheel(self):
        if self.wheel is not None:
            self.wheel.close()
            self.wheel = None

    def save_wheel_settings(self, enabled, categories):
        def save():
            known = {category["id"] for category in self.messages.categories}
            if any(cid not in known for cid in categories):
                raise ValueError("有预设类别已删除，请重新选择。")
            replacement = self._create_wheel() if enabled and self.wheel is None else None
            try:
                self.wheel_settings.save(enabled, categories)
            except (OSError, ValueError):
                if replacement is not None:
                    replacement.close()
                raise
            if replacement is not None:
                self.wheel = replacement
            if not enabled:
                self._close_wheel()
                self.messages.select_wheel_categories(())
        self.sender.edit(save)

    def save_settings(self, value):
        validate_config(value)
        previous = self.config.value.copy()
        changed = {key for key in value if value[key] != previous[key]}
        if not changed:
            return
        hotkeys_changed = bool(changed & {"team_hotkey", "all_hotkey"})
        autostart_changed = value["autostart"] != previous["autostart"]
        autostart_applied = False
        try:
            if hotkeys_changed and not self.hotkeys.configure(value):
                raise ValueError("快捷键注册失败：\n" + "\n".join(self.hotkeys.status.values()))
            if autostart_changed:
                set_autostart(value["autostart"])
                autostart_applied = True
            self.config.save(value)
        except (OSError, ValueError) as exc:
            if hotkeys_changed:
                self.hotkeys.configure(previous)
            if self.window is not None:
                self.window.set_hotkey_status(self.hotkeys.status)
            if autostart_applied:
                try:
                    set_autostart(previous["autostart"])
                except OSError as rollback:
                    raise OSError(f"{exc}\n恢复开机启动设置失败：{rollback}") from exc
            raise
        if "cooldown" in changed:
            self.sender.cooldown = value["cooldown"]
        if "category_mode" in changed:
            self.messages.set_mode(value["category_mode"])
        if "font_size" in changed:
            self.tray.set_font_size(value["font_size"])
        if hotkeys_changed and self.window is not None:
            self.window.set_hotkey_status(self.hotkeys.status)

    def cleanup(self):
        self.quit_timer.stop()
        self._close_wheel()
        self.hotkeys.close()
        self.sender.stop()
        if self.window is not None:
            self.window.shutdown()
        self.hotkey_window.deleteLater()
        self.tray.hide()
        logger = logging.getLogger("ValorantToxicTamer")
        logger.info("application stopped")
        logger.removeHandler(self.log_handler)
        self.log_handler.close()

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        self._close_wheel()
        self.sender.cancel.set()
        if self.window is not None:
            self.window.begin_shutdown()
            self.window.result_label.setText("正在退出，等待后台任务清理…")
            self.window.setEnabled(False)
        self.quit_timer.start()
        self._finish_quit()

    def _finish_quit(self):
        # Keep Qt responsive while owned workers cancel and release resources.
        if self.sender.thread and self.sender.thread.is_alive():
            return
        if self.window is not None:
            workers = (self.window.management.import_worker, self.window.updater.worker)
            if any(worker is not None and worker.isRunning() for worker in workers):
                return
        self.quit_timer.stop()
        self.app.quit()


def main():
    # Diagnostic modes never send keyboard input and need no UAC.
    diagnostic = len(sys.argv) == 3 and sys.argv[1] in (
        "--startup-check", "--update-check-smoke")
    if not diagnostic:
        from .elevation import ensure_administrator
        status = ensure_administrator()
        if status is not None:
            return status
    app = QApplication(sys.argv)
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    app.setApplicationName("ValorantToxicTamer")
    app.setApplicationVersion(VERSION)
    app.setQuitOnLastWindowClosed(False)
    if len(sys.argv) == 3 and sys.argv[1] == "--startup-check":
        from .startup_check import run
        return run(app, sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--update-check-smoke":
        from .startup_check import run_update_check
        return run_update_check(app, sys.argv[2])
    if sys.platform != "win32":
        QMessageBox.critical(None, "平台不支持", "本程序仅支持 Windows 10 / 11。")
        return 1
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "托盘不可用", "未检测到系统托盘，程序无法后台运行。")
        return 1
    directory = data_directory()
    try:
        if getattr(sys, "frozen", False):
            from .data_migration import has_data, legacy_directory, migrate_data
            source = legacy_directory()
            if (not directory.parent.joinpath(".vtt-migration-skipped").exists()
                    and not has_data(directory) and has_data(source) and source.resolve() != directory.resolve()):
                answer = QMessageBox.question(None, "迁移旧数据", f"检测到旧版个人数据：\n{source}\n\n"
                    f"是否迁移到：\n{directory}\n\n迁移并校验成功后，将删除已迁移的旧数据。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer == QMessageBox.StandardButton.Yes:
                    migrate_data(source, directory)
        directory.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(directory / "application.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            QMessageBox.warning(None, "无法启动", "程序已在运行，或数据目录无法写入。请检查系统托盘及目录权限。")
            return 1
        controller = Application(app, directory)
        # Inno Setup checks this mutex before replacing or uninstalling files.
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        mutex = kernel.CreateMutexW(None, False, "Local\\ValorantToxicTamer")
        if not mutex:
            raise ctypes.WinError(ctypes.get_last_error())
    except (OSError, ValueError, RuntimeError) as exc:
        QMessageBox.critical(None, "启动失败", str(exc))
        return 1
    result = app.exec()
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle(mutex)
    lock.unlock()
    del controller
    return result


if __name__ == "__main__":
    raise SystemExit(main())

import sys
import logging

from PySide6.QtCore import QLockFile, QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon, QWidget

from .config_manager import ConfigManager, data_directory, set_autostart, validate_config
from .diagnostics import configure_logging
from .hotkey import Hotkeys
from .message_manager import MessageManager
from .sender import Sender
from .tray import Tray
from .win32_api import WindowsAPI
from .app_version import VERSION


class Notifications(QObject):
    message = Signal(str)


class Application(QObject):
    def __init__(self, app, directory):
        super().__init__()
        self.app = app
        self.config = ConfigManager(directory / "config.json")
        self.messages = MessageManager(directory / "messages.json")
        self.log_handler = configure_logging(directory)
        self.api = WindowsAPI()
        self.notifications = Notifications()
        self.sender = Sender(self.messages, self.api, self.config.value["cooldown"],
                             self.notifications.message.emit)
        self.window = None
        self.last_message = None
        # Keep the native hotkey handle alive independently of the optional UI.
        self.hotkey_window = QWidget()
        self.hotkeys = Hotkeys(app, int(self.hotkey_window.winId()), self.api, self.trigger)
        self.tray = Tray(self.reveal, self.quit, self, font_size=self.config.value["font_size"])
        self.notifications.message.connect(self.report)
        app.aboutToQuit.connect(self.cleanup)
        registered = self.hotkeys.configure(self.config.value)
        if not self.config.value["start_hidden"] or not registered:
            self.reveal(0 if registered else 1)
        self.tray.showMessage("ValorantToxicTamer", "已启动。双击托盘图标管理消息。" if registered
                              else "快捷键注册失败，请在设置中选择其他按键。")

    @Slot(str)
    def report(self, message):
        logging.getLogger("ValorantToxicTamer").info("status: %s", message)
        self.last_message = message
        visible = self.window is not None and self.window.isVisible()
        if visible:
            self.window.report(message)
        if not visible and not message.startswith(("已忽略", "队伍输入", "全体输入")):
            self.tray.showMessage("ValorantToxicTamer", message, QSystemTrayIcon.MessageIcon.Warning)

    def reveal(self, page=0):
        if self.window is None:
            from .ui import MainWindow
            self.window = MainWindow(self.messages, self.config, self.sender, self.save_settings)
            self.window.updater.ready_to_install.connect(self.quit)
        self.window.set_hotkey_status(self.hotkeys.status)
        self.window.reveal(page)
        if self.last_message is not None:
            self.window.report(self.last_message)

    def trigger(self, channel):
        triggered = self.sender.trigger(channel)
        if self.window is not None and self.window.isVisible():
            self.window.refresh_status()
        return triggered

    def save_settings(self, value):
        validate_config(value)
        previous = self.config.value.copy()
        autostart_changed = value["autostart"] != previous["autostart"]
        autostart_applied = False
        try:
            if not self.hotkeys.configure(value):
                raise ValueError("快捷键注册失败：\n" + "\n".join(self.hotkeys.status.values()))
            if autostart_changed:
                set_autostart(value["autostart"])
                autostart_applied = True
            self.config.save(value)
        except (OSError, ValueError) as exc:
            self.hotkeys.configure(previous)
            if self.window is not None:
                self.window.set_hotkey_status(self.hotkeys.status)
            if autostart_applied:
                try:
                    set_autostart(previous["autostart"])
                except OSError as rollback:
                    raise OSError(f"{exc}\n恢复开机启动设置失败：{rollback}") from exc
            raise
        self.sender.cooldown = value["cooldown"]
        self.tray.set_font_size(self.config.value["font_size"])
        if self.window is not None:
            self.window.set_hotkey_status(self.hotkeys.status)

    def cleanup(self):
        self.hotkeys.close()
        self.sender.stop()
        if self.window is not None:
            self.window.timer.stop()
            self.window.updater.shutdown()
        self.hotkey_window.deleteLater()
        self.tray.hide()
        logger = logging.getLogger("ValorantToxicTamer")
        logger.info("application stopped")
        logger.removeHandler(self.log_handler)
        self.log_handler.close()

    def quit(self):
        self.app.quit()


def main():
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
        directory.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(directory / "application.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            QMessageBox.warning(None, "无法启动", "程序已在运行，或数据目录无法写入。请检查系统托盘及目录权限。")
            return 1
        controller = Application(app, directory)
    except (OSError, ValueError, RuntimeError) as exc:
        QMessageBox.critical(None, "启动失败", str(exc))
        return 1
    result = app.exec()
    lock.unlock()
    del controller
    return result


if __name__ == "__main__":
    raise SystemExit(main())

import sys
import logging

from PySide6.QtCore import QLockFile, QObject, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from config_manager import ConfigManager, data_directory, set_autostart, validate_config
from diagnostics import configure_logging
from hotkey import Hotkeys
from message_manager import MessageManager
from sender import Sender
from tray import Tray
from ui import MainWindow
from win32_api import WindowsAPI
from app_version import VERSION


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
        self.window = MainWindow(self.messages, self.config, self.sender, self.save_settings)
        self.window.updater.ready_to_install.connect(self.quit)
        self.hotkeys = Hotkeys(app, int(self.window.winId()), self.api, self.sender.trigger)
        self.tray = Tray(self.window, self.quit)
        self.notifications.message.connect(self.report)
        app.aboutToQuit.connect(self.cleanup)
        registered = self.hotkeys.configure(self.config.value)
        self.window.set_hotkey_status(self.hotkeys.status)
        if not self.config.value["start_hidden"] or not registered:
            self.window.reveal()
        self.tray.showMessage("ValorantToxicTamer", "已启动。双击托盘图标管理消息。" if registered
                              else "快捷键注册失败，请在设置中选择其他按键。")

    @Slot(str)
    def report(self, message):
        logging.getLogger("ValorantToxicTamer").info("status: %s", message)
        self.window.report(message)
        if not self.window.isVisible() and not message.startswith(("已忽略", "队伍输入", "全体输入")):
            self.tray.showMessage("ValorantToxicTamer", message, QSystemTrayIcon.MessageIcon.Warning)

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
            self.window.set_hotkey_status(self.hotkeys.status)
            if autostart_applied:
                try:
                    set_autostart(previous["autostart"])
                except OSError as rollback:
                    raise OSError(f"{exc}\n恢复开机启动设置失败：{rollback}") from exc
            raise
        self.sender.cooldown = value["cooldown"]
        self.window.set_hotkey_status(self.hotkeys.status)

    def cleanup(self):
        self.hotkeys.close()
        self.sender.stop()
        self.window.updater.shutdown()
        self.tray.hide()
        logger = logging.getLogger("ValorantToxicTamer")
        logger.info("application stopped")
        logger.removeHandler(self.log_handler)
        self.log_handler.close()

    def quit(self):
        self.app.quit()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ValorantToxicTamer")
    app.setApplicationVersion(VERSION)
    app.setQuitOnLastWindowClosed(False)
    if len(sys.argv) == 3 and sys.argv[1] == "--startup-check":
        from startup_check import run
        return run(app, sys.argv[2])
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

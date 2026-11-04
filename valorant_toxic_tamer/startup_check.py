"""Exercise the shipped EXE with temporary data and no keyboard input."""
import json
from ctypes import wintypes as W
from pathlib import Path
import tempfile
import sys

from PySide6.QtCore import QTimer, qVersion
from PySide6.QtWidgets import QSystemTrayIcon


def run(app, report_path):
    from .app import Application
    from .config_manager import DEFAULT_CONFIG

    path = Path(report_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    result = {"qt_version": qVersion(), "system_tray_available": QSystemTrayIcon.isSystemTrayAvailable()}
    if not result["system_tray_available"]:
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 1
    with tempfile.TemporaryDirectory(prefix="startup-check-", dir=path.parent) as temporary:
        # Avoid competing with the user's running instance on F8/F9.
        (Path(temporary) / "config.json").write_text(json.dumps(
            {**DEFAULT_CONFIG, "team_hotkey": "F10", "all_hotkey": "F11"}), encoding="utf-8")
        controller = Application(app, Path(temporary))
        result["empty_messages"] = controller.messages.messages == []
        result["hotkeys"] = controller.hotkeys.status.copy()
        result["hotkeys_registered"] = len(controller.hotkeys.registered) == 2
        result["starts_hidden"] = controller.window is None
        result["ui_not_loaded_at_startup"] = "valorant_toxic_tamer.ui" not in sys.modules
        result["updater_not_loaded_at_startup"] = "valorant_toxic_tamer.updater" not in sys.modules
        result["update_helper_bundled"] = Path(__file__).with_name("update_install.ps1").exists()
        received = []
        controller.hotkeys.callback = received.append
        post = controller.api.user.PostMessageW
        post.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        post.restype = W.BOOL

        def post_hotkeys():
            result["hotkeys_posted"] = all(post(controller.hotkeys.hwnd, 0x0312, identifier, 0)
                                            for identifier in controller.hotkeys.IDS)

        def show_settings():
            result["hotkeys_delivered_without_window"] = received == ["team", "all"] and controller.window is None
            controller.tray.menu.actions()[2].trigger()

        def finish():
            result["settings_opened"] = controller.window.isVisible() and controller.window.tabs.currentIndex() == 1
            result["update_button_available"] = controller.window.update_button.isEnabled()
            result["updater_not_loaded_after_settings"] = "valorant_toxic_tamer.updater" not in sys.modules
            controller.window.close()
            result["close_hides"] = not controller.window.isVisible()
            result["hidden_timer_stopped"] = not controller.window.timer.isActive()
            result["tray_visible"] = controller.tray.isVisible()
            controller.tray.menu.actions()[-1].trigger()

        QTimer.singleShot(50, post_hotkeys)
        QTimer.singleShot(200, show_settings)
        QTimer.singleShot(600, finish)
        app.exec()
        result["hotkeys_released"] = controller.hotkeys.registered == {}
        result["sender_stopped"] = controller.sender.cancel.is_set()
        controller.window.timer.stop()
        controller.window.deleteLater()
        app.processEvents()
    result["passed"] = all(value for value in result.values() if isinstance(value, bool))
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["passed"] else 1


def run_update_check(app, report_path):
    """Opt-in native repeated lookup probe; no hotkeys, installation or user data."""
    import ctypes as C
    from .config_manager import ConfigManager
    from .message_manager import MessageManager
    from .sender import Sender
    from .ui import MainWindow

    class Counters(C.Structure):
        _fields_ = [("cb", W.DWORD), ("PageFaultCount", W.DWORD)] + [
            (name, C.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
            "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
            "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]

    kernel = C.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = W.HANDLE
    psapi = C.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [W.HANDLE, C.POINTER(Counters), W.DWORD]

    def memory(stage):
        counters = Counters()
        counters.cb = C.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), C.byref(counters), C.sizeof(counters)):
            raise OSError("GetProcessMemoryInfo failed")
        return {"stage": stage, "working_set_MiB": round(counters.WorkingSetSize / 2**20, 2),
                "private_commit_MiB": round(counters.PrivateUsage / 2**20, 2)}

    path = Path(report_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    result = {"samples": [], "errors": [], "checks": 0}
    with tempfile.TemporaryDirectory(prefix="update-check-", dir=path.parent) as temporary:
        root = Path(temporary)
        (root / "update_settings.json").write_text('{"channel":"beta"}', encoding="utf-8")
        config = ConfigManager(root / "config.json")
        messages = MessageManager(root / "messages.json")
        sender = Sender(messages, object())
        window = MainWindow(messages, config, sender, config.save)
        window.error = result["errors"].append
        window.information = lambda *args: None
        window.reveal(1)

        def start():
            result["samples"].append(memory("before_check"))
            window.update_button.click()
            monitor.start(100)

        def monitor_check():
            modal = app.activeModalWidget()
            if modal is not None:
                from PySide6.QtWidgets import QMessageBox
                modal.done(QMessageBox.StandardButton.No)
            if window.updater.busy:
                return
            monitor.stop()
            result["checks"] += 1
            result["samples"].append(memory(f"after_check_{result['checks']}"))
            if result["checks"] < 3:
                window.update_button.click()
                monitor.start(100)
            else:
                result["tls_not_loaded_in_gui"] = all(name not in sys.modules for name in (
                    "ssl", "truststore", "valorant_toxic_tamer.updater"))
                app.quit()

        monitor = QTimer()
        monitor.timeout.connect(monitor_check)
        QTimer.singleShot(200, start)
        app.exec()
        monitor.stop()
        window.updater.shutdown()
        sender.stop()
        window.hide()
        window.deleteLater()
        app.processEvents()
    result["passed"] = result["checks"] == 3 and not result["errors"] and result.get("tls_not_loaded_in_gui", False)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["passed"] else 1

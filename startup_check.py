"""Exercise the shipped EXE with temporary data and no keyboard input."""
import json
from pathlib import Path
import tempfile

from PySide6.QtCore import QTimer, qVersion
from PySide6.QtWidgets import QSystemTrayIcon


def run(app, report_path):
    from main import Application

    path = Path(report_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    result = {"qt_version": qVersion(), "system_tray_available": QSystemTrayIcon.isSystemTrayAvailable()}
    if not result["system_tray_available"]:
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 1
    with tempfile.TemporaryDirectory(prefix="startup-check-", dir=path.parent) as temporary:
        controller = Application(app, Path(temporary))
        result["empty_messages"] = controller.messages.messages == []
        result["hotkeys"] = controller.hotkeys.status.copy()
        result["hotkeys_registered"] = len(controller.hotkeys.registered) == 2
        result["starts_hidden"] = not controller.window.isVisible()
        result["update_button_available"] = controller.window.update_button.isEnabled()
        result["update_helper_bundled"] = Path(__file__).with_name("update_install.ps1").exists()

        def show_settings():
            controller.tray.menu.actions()[2].trigger()

        def finish():
            result["settings_opened"] = controller.window.isVisible() and controller.window.tabs.currentIndex() == 1
            controller.window.close()
            result["close_hides"] = not controller.window.isVisible()
            result["tray_visible"] = controller.tray.isVisible()
            controller.tray.menu.actions()[-1].trigger()

        QTimer.singleShot(150, show_settings)
        QTimer.singleShot(450, finish)
        app.exec()
        result["hotkeys_released"] = controller.hotkeys.registered == {}
        result["sender_stopped"] = controller.sender.cancel.is_set()
        controller.window.timer.stop()
        controller.window.deleteLater()
        app.processEvents()
    result["passed"] = all(value for value in result.values() if isinstance(value, bool))
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["passed"] else 1

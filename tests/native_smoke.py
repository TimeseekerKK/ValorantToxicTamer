"""Opt-in native tray/window check with an empty temporary message list.

Run from the project root: .venv\Scripts\python.exe tests\native_smoke.py
This test never invokes SendInput and removes its hotkeys on exit.
"""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from valorant_toxic_tamer.app import Application


app = QApplication([])
app.setQuitOnLastWindowClosed(False)
root = Path(__file__).resolve().parents[1]
result = {"system_tray_available": QSystemTrayIcon.isSystemTrayAvailable()}
if not result["system_tray_available"]:
    raise SystemExit("System tray unavailable; native smoke test cannot run")

with tempfile.TemporaryDirectory(dir=root / "tests") as directory:
    controller = Application(app, Path(directory))
    result["hotkeys"] = controller.hotkeys.status.copy()
    result["empty_messages"] = controller.messages.messages == []
    result["starts_hidden"] = controller.window is None

    def show():
        controller.tray.menu.actions()[2].trigger()

    def hide():
        result["settings_opened"] = controller.window.isVisible() and controller.window.tabs.currentIndex() == 1
        controller.window.close()
        result["close_hides"] = not controller.window.isVisible()
        result["hidden_timer_stopped"] = not controller.window.timer.isActive()
        result["tray_visible"] = controller.tray.isVisible()
        controller.tray.menu.actions()[-1].trigger()

    QTimer.singleShot(150, show)
    QTimer.singleShot(450, hide)
    app.exec()
    result["hotkeys_released"] = controller.hotkeys.registered == {}
    result["sender_stopped"] = controller.sender.cancel.is_set()
    controller.window.timer.stop()
    controller.window.deleteLater()
    app.processEvents()

output = root / "artifacts" / "checks"
output.mkdir(parents=True, exist_ok=True)
(output / "native-smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
if not all(value for value in result.values() if isinstance(value, bool)):
    raise SystemExit(1)

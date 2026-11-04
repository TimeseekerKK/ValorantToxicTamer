"""Test WM_HOTKEY delivery to our own Qt window; no keyboard input or Sender."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget
from valorant_toxic_tamer.config_manager import DEFAULT_CONFIG
from valorant_toxic_tamer.hotkey import Hotkeys
from valorant_toxic_tamer.win32_api import WindowsAPI

app = QApplication([])
window = QWidget()
api = WindowsAPI()
received = []
observed = []


class ProbeHotkeys(Hotkeys):
    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = W.MSG.from_address(int(message))
            if msg.message == 0x312 and msg.wParam in self.IDS:
                now = api.kernel.GetTickCount64() & 0xFFFFFFFF
                observed.append({"type": bytes(event_type).decode(), "time": msg.time,
                                 "tick": now, "age": (now - msg.time) & 0xFFFFFFFF})
        return super().nativeEventFilter(event_type, message)


hotkeys = ProbeHotkeys(app, int(window.winId()), api, received.append)
hotkeys.configure({**DEFAULT_CONFIG, "team_hotkey": "F10", "all_hotkey": "F11"})
api.user.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
api.user.PostMessageW.restype = W.BOOL


def post():
    for identifier, vk in ((0x5101, 0x79), (0x5102, 0x7A)):
        if not api.user.PostMessageW(int(window.winId()), 0x312, identifier, vk << 16):
            raise C.WinError(C.get_last_error())


QTimer.singleShot(100, post)
QTimer.singleShot(400, app.quit)
app.exec()
hotkeys.close()
result = {"events": observed, "callbacks": received, "passed": received == ["team", "all"]}
output = Path(__file__).resolve().parents[1] / "artifacts" / "hotkey-delivery.json"
output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["passed"] else 1)

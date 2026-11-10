import ctypes as C
from ctypes import wintypes as W
import logging

from PySide6.QtCore import QAbstractNativeEventFilter

logger = logging.getLogger("ValorantToxicTamer.hotkey")


class Hotkeys(QAbstractNativeEventFilter):
    IDS = {0x5101: "team", 0x5102: "all"}

    def __init__(self, app, hwnd, api, callback):
        super().__init__()
        self.app, self.hwnd, self.api, self.callback = app, hwnd, api, callback
        self.registered = {}
        self.status = {}
        app.installNativeEventFilter(self)

    def configure(self, config):
        # Keep unchanged registrations; release all changing keys before swaps.
        for identifier in tuple(self.registered):
            if self.registered[identifier] != config[f"{self.IDS[identifier]}_hotkey"]:
                self.api.user.UnregisterHotKey(self.hwnd, identifier)
                del self.registered[identifier]
        self.status = {}
        for identifier, channel in self.IDS.items():
            name = config[f"{channel}_hotkey"]
            vk = 0x70 + int(name[1:]) - 1
            if (self.registered.get(identifier) == name or
                    self.api.user.RegisterHotKey(self.hwnd, identifier, 0x4000, vk)):
                self.registered[identifier] = name
                self.status[channel] = f"{name} · 已注册"
            else:
                self.status[channel] = f"{name} · 注册失败（冲突或系统限制，错误 {C.get_last_error()}）"
            logger.info("registration channel=%s status=%s", channel, self.status[channel])
        return len(self.registered) == 2

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = W.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam in self.registered:
                # Don't execute hotkeys queued while a modal dialog/UI was blocked.
                age = ((self.api.kernel.GetTickCount64() & 0xFFFFFFFF) - msg.time) & 0xFFFFFFFF
                logger.info("received key=%s channel=%s event_age_ms=%s", self.registered[msg.wParam],
                            self.IDS[msg.wParam], age)
                if age <= 150:
                    self.callback(self.IDS[msg.wParam])
                else:
                    logger.info("stale hotkey ignored")
                return True, 0
        return False, 0

    def unregister(self):
        for identifier in self.registered:
            self.api.user.UnregisterHotKey(self.hwnd, identifier)
        self.registered.clear()

    def close(self):
        self.unregister()
        self.app.removeNativeEventFilter(self)

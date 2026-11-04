"""Minimal documented Win32 APIs; no process memory reads or hooks."""
import ctypes as C
from ctypes import wintypes as W
import logging
import sys

logger = logging.getLogger("ValorantToxicTamer.win32")


class PROCESSENTRY32W(C.Structure):
    _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD),
                ("th32ProcessID", W.DWORD), ("th32DefaultHeapID", C.c_size_t),
                ("th32ModuleID", W.DWORD), ("cntThreads", W.DWORD),
                ("th32ParentProcessID", W.DWORD), ("pcPriClassBase", W.LONG),
                ("dwFlags", W.DWORD), ("szExeFile", W.WCHAR * 260)]


class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD),
                ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class INPUTUNION(C.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", INPUTUNION)]


def key_event(vk=0, scan=0, flags=0):
    return INPUT(type=1, ki=KEYBDINPUT(vk, scan, flags, 0, 0))


class WindowsAPI:
    GAME_EXE = "valorant-win64-shipping.exe"

    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("本程序仅支持 Windows 10 / 11")
        self.user = C.WinDLL("user32", use_last_error=True)
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.target_error = "尚未检查前台窗口"
        signatures = [
            (self.user.GetForegroundWindow, [], W.HWND),
            (self.user.GetWindowThreadProcessId, [W.HWND, C.POINTER(W.DWORD)], W.DWORD),
            (self.kernel.CreateToolhelp32Snapshot, [W.DWORD, W.DWORD], W.HANDLE),
            (self.kernel.Process32FirstW, [W.HANDLE, C.POINTER(PROCESSENTRY32W)], W.BOOL),
            (self.kernel.Process32NextW, [W.HANDLE, C.POINTER(PROCESSENTRY32W)], W.BOOL),
            (self.kernel.CloseHandle, [W.HANDLE], W.BOOL),
            (self.user.SendInput, [W.UINT, C.POINTER(INPUT), C.c_int], W.UINT),
            (self.user.GetAsyncKeyState, [C.c_int], W.SHORT),
            (self.user.MapVirtualKeyW, [W.UINT, W.UINT], W.UINT),
            (self.user.RegisterHotKey, [W.HWND, C.c_int, W.UINT, W.UINT], W.BOOL),
            (self.user.UnregisterHotKey, [W.HWND, C.c_int], W.BOOL),
            (self.kernel.GetTickCount64, [], C.c_ulonglong),
        ]
        for function, arguments, result in signatures:
            function.argtypes, function.restype = arguments, result

    def foreground(self):
        hwnd = self.user.GetForegroundWindow()
        pid = W.DWORD()
        if not hwnd:
            self.target_error = "Windows 当前没有前台窗口"
            return None
        if not self.user.GetWindowThreadProcessId(hwnd, C.byref(pid)):
            self.target_error = f"无法取得前台窗口所属进程（Windows 错误 {C.get_last_error()}）"
            return None
        return hwnd, pid.value

    def process_name(self, pid):
        # Public process list only: no target process handle, modules or memory.
        snapshot = self.kernel.CreateToolhelp32Snapshot(0x00000002, 0)
        if snapshot in (None, C.c_void_p(-1).value):
            raise OSError(f"读取 Windows 进程列表失败（错误 {C.get_last_error()}）")
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = C.sizeof(entry)
            available = self.kernel.Process32FirstW(snapshot, C.byref(entry))
            while available:
                if entry.th32ProcessID == pid:
                    return entry.szExeFile
                available = self.kernel.Process32NextW(snapshot, C.byref(entry))
            error = C.get_last_error()
            if error not in (0, 18):  # ERROR_NO_MORE_FILES is normal exhaustion.
                raise OSError(f"枚举 Windows 进程失败（错误 {error}）")
            return None
        finally:
            self.kernel.CloseHandle(snapshot)

    def target(self):
        target = self.foreground()
        if not target:
            logger.info("foreground rejected: %s", self.target_error)
            return None
        try:
            name = self.process_name(target[1])
        except OSError as exc:
            self.target_error = str(exc)
            logger.warning("foreground rejected hwnd=%s pid=%s: %s", *target, self.target_error)
            return None
        if name is None:
            self.target_error = f"前台进程 PID {target[1]} 已退出，或进程列表中未找到它"
        elif name.casefold() != self.GAME_EXE:
            self.target_error = f"当前前台为 {name}（PID {target[1]}），不是无畏契约游戏窗口"
        elif self.is_foreground(target):
            self.target_error = ""
            logger.info("foreground accepted hwnd=%s pid=%s exe=%s", *target, name)
            return target
        else:
            self.target_error = "检查过程中前台窗口发生变化，请切回游戏后重试"
        logger.info("foreground rejected: %s", self.target_error)
        return None

    def is_foreground(self, target):
        # During one send, retain the verified HWND + PID; don't rescan every character.
        return self.foreground() == target

    def modifiers_down(self):
        return any(self.user.GetAsyncKeyState(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C))

    def emit(self, events):
        inputs = (INPUT * len(events))(*events)
        C.set_last_error(0)
        sent = self.user.SendInput(len(inputs), inputs, C.sizeof(INPUT))
        if sent != len(inputs):
            logger.warning("SendInput submitted=%s requested=%s error=%s", sent, len(inputs), C.get_last_error())
            raise OSError(f"SendInput 仅提交 {sent}/{len(inputs)} 个事件（Windows 错误 {C.get_last_error()}）")

    def key(self, vk, down):
        self.keys((vk,), down)

    def keys(self, virtual_keys, down):
        # Build the entire batch before submitting any events.
        events = [self._key_event(vk, down) for vk in virtual_keys]
        self.emit(events)

    def _key_event(self, vk, down):
        flags = 0 if down else 2
        if vk == 0x10:
            # Use an explicit left Shift scan code for the all-chat chord.
            # Keep Enter's already verified virtual-key input unchanged.
            scan = self.user.MapVirtualKeyW(0xA0, 0)  # VK_LSHIFT -> scan code
            if not scan:
                raise OSError("无法取得左 Shift 扫描码")
            return key_event(scan=scan, flags=flags | 0x0008)
        else:
            return key_event(vk=vk, flags=flags)

    def text_character(self, character):
        units = character.encode("utf-16-le")
        events = []
        for i in range(0, len(units), 2):
            unit = int.from_bytes(units[i:i + 2], "little")
            events.extend([key_event(scan=unit, flags=4), key_event(scan=unit, flags=6)])
        try:
            self.emit(events)
        except OSError:
            # A partial batch can leave a Unicode key down. Best-effort release.
            for event in events[1::2]:
                try:
                    self.emit([event])
                except OSError:
                    pass
            raise

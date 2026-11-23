"""Passive Windows category wheel. The game keeps its mouse input and focus."""
import ctypes as C
from ctypes import wintypes as W
import logging
import math
import time

from PySide6.QtCore import QAbstractNativeEventFilter, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


logger = logging.getLogger("ValorantToxicTamer.category_wheel")
WM_INPUT = 0x00FF
VK_ALT = 0x12
VK_LEFT_ALT = 0xA4
KEY_UP = 1
KEY_EXTENDED = 2
MOUSE_LEFT_DOWN = 0x0001
MOUSE_RIGHT_DOWN = 0x0004
CHORD_KEYS = {0x09, 0x10, 0x11, VK_ALT, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA5}


class WheelDraft:
    def __init__(self, options, active, names):
        self.options = (*options, (None, "恢复循环", True))
        self.active = active
        self.names = names
        self.hover = None
        self.order = []
        self.sorting = False
        self.x = self.y = 0.0
        self.step = 360 / len(self.options)

    def move(self, dx, dy):
        self.x += dx
        self.y += dy
        distance = math.hypot(self.x, self.y)
        if distance > 106:
            self.x *= 106 / distance
            self.y *= 106 / distance
        if distance < (19 if self.hover is not None else 26):
            self.hover = None
        else:
            angle = math.degrees(math.atan2(self.x, -self.y))
            self.hover = math.floor((angle + self.step / 2) / self.step) % len(self.options)

    def click(self, buttons):
        if self.hover is None:
            return
        cid, _, available = self.options[self.hover]
        if cid is None or not available:
            return
        if buttons & MOUSE_LEFT_DOWN:
            if cid not in self.order:
                self.order.append(cid)
            self.sorting = True
        elif buttons & MOUSE_RIGHT_DOWN and cid in self.order:
            self.order.remove(cid)

    def selection(self):
        if self.sorting:
            return tuple(self.order) if len(self.order) >= 2 else None
        if self.hover is not None:
            cid, _, available = self.options[self.hover]
            if available:
                return (cid,) if cid is not None else ()
        return None


class WheelOverlay(QWidget):
    SIZE = 432

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.draft = None

    @staticmethod
    def draw_text(painter, rect, text, color, size, bold=False):
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(size)
        font.setBold(bold)
        painter.setFont(font)
        painter.setPen(QColor(color))
        display = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width()))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, display)

    @staticmethod
    def sector(outer, inner, angle, step):
        start, sweep = 90 - angle + step / 2 - 0.7, -(step - 1.4)
        end = math.radians(start + sweep)
        path = QPainterPath()
        path.arcMoveTo(outer, start)
        path.arcTo(outer, start, sweep)
        path.lineTo(inner.center() + QPointF(inner.width() / 2 * math.cos(end),
                                              -inner.height() / 2 * math.sin(end)))
        path.arcTo(inner, start + sweep, -sweep)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        draft = self.draft
        if draft is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        middle = self.SIZE / 2
        outer = QRectF(7, 7, self.SIZE - 14, self.SIZE - 14)
        inner = QRectF(middle - 87, middle - 87, 174, 174)
        order = draft.order if draft.sorting else draft.active if len(draft.active) > 1 else ()
        label_width = min(137, 292 * math.sin(math.pi / max(2, len(draft.options))) - 14)
        for index, (cid, label, available) in enumerate(draft.options):
            angle = draft.step * index
            enabled = available and (cid is not None or not draft.sorting)
            hover = draft.hover == index and enabled
            fill = QColor("#101923" if not enabled else "#472A36" if hover else "#16232F")
            fill.setAlphaF(0.94)
            painter.setBrush(fill)
            painter.setPen(QPen(QColor("#FF4655" if hover else "#536171"), 3 if hover else 1.5))
            painter.drawPath(self.sector(outer, inner, angle, draft.step))
            radians = math.radians(angle)
            point = QPointF(middle + 148 * math.sin(radians), middle - 148 * math.cos(radians))
            marker = str(order.index(cid) + 1) if cid in order else ""
            if not draft.sorting and len(draft.active) == 1 and cid == draft.active[0]:
                marker = "✓"
            if not available and not marker:
                marker = "无消息"
            y = point.y() - (24 if marker else 14)
            self.draw_text(painter, QRectF(point.x() - label_width / 2, y, label_width, 28),
                           label, "#EDF2F6" if enabled else "#718092", 19, True)
            if marker:
                badge = QRectF(point.x() - 12, point.y() + 7, 24, 24)
                if marker.isnumeric():
                    painter.setPen(Qt.PenStyle.NoPen if draft.sorting else QPen(QColor("#68DED2"), 1.5))
                    painter.setBrush(QColor("#B8D9F1" if draft.sorting else "#16232F"))
                    painter.drawEllipse(badge)
                    self.draw_text(painter, badge, marker, "#16232F" if draft.sorting else "#68DED2", 14, True)
                else:
                    self.draw_text(painter, QRectF(point.x() - 43, point.y() + 4, 86, 24),
                                   marker, "#68DED2" if marker == "✓" else "#718092", 14, True)
        painter.setBrush(QColor("#0C141D"))
        painter.setPen(QPen(QColor("#536171"), 1.5))
        painter.drawEllipse(inner)
        hint = "松开 Alt 取消"
        if draft.sorting:
            hint = "松开 Alt 确认" if len(order) >= 2 else "至少选择 2 类"
        elif draft.hover is not None:
            cid, _, available = draft.options[draft.hover]
            if available:
                hint = "松开 Alt 恢复循环" if cid is None else "松开 Alt 锁定单类"
        elif order:
            hint = "当前交替顺序"
        if order:
            names = " → ".join(draft.names.get(cid, "已删除") for cid in order)
            self.draw_text(painter, QRectF(middle - 72, middle - 49, 144, 24), names, "#EDF2F6", 14)
        self.draw_text(painter, QRectF(middle - 76, middle - 24, 152, 24), hint, "#EDF2F6", 16)
        self.draw_text(painter, QRectF(middle - 76, middle + 5, 152, 24),
                       "左键加入 · 右键移除", "#96A4B2", 14)
        painter.end()


class RawInputDevice(C.Structure):
    _fields_ = [("page", W.USHORT), ("usage", W.USHORT), ("flags", W.DWORD), ("target", W.HWND)]


class RawInputHeader(C.Structure):
    _fields_ = [("kind", W.DWORD), ("size", W.DWORD), ("device", W.HANDLE), ("flags", W.WPARAM)]


class RawMouse(C.Structure):
    _fields_ = [("flags", W.USHORT), ("buttons", W.ULONG), ("raw_buttons", W.ULONG),
                ("x", W.LONG), ("y", W.LONG), ("extra", W.ULONG)]


class RawKeyboard(C.Structure):
    _fields_ = [("scan", W.USHORT), ("flags", W.USHORT), ("reserved", W.USHORT), ("vk", W.USHORT),
                ("message", W.UINT), ("extra", W.ULONG)]


class MonitorInfo(C.Structure):
    _fields_ = [("size", W.DWORD), ("monitor", W.RECT), ("work", W.RECT), ("flags", W.DWORD)]


class WheelInput(QAbstractNativeEventFilter):
    def __init__(self, wheel, hwnd):
        super().__init__()
        self.wheel = wheel
        self.hwnd = hwnd
        self.user = wheel.api.user
        self.registered = set()
        self.buffer = C.create_string_buffer(64)
        self.user.RegisterRawInputDevices.argtypes = [C.POINTER(RawInputDevice), W.UINT, W.UINT]
        self.user.RegisterRawInputDevices.restype = W.BOOL
        self.user.GetRawInputData.argtypes = [W.HANDLE, W.UINT, C.c_void_p, C.POINTER(W.UINT), W.UINT]
        self.user.GetRawInputData.restype = W.UINT

    def register(self, usage, enabled):
        if enabled == (usage in self.registered):
            return
        device = RawInputDevice(1, usage, 0x100 if enabled else 1, self.hwnd if enabled else None)
        if not self.user.RegisterRawInputDevices(C.byref(device), 1, C.sizeof(device)):
            raise OSError(C.get_last_error(), "注册轮盘输入失败" if enabled else "注销轮盘输入失败")
        if enabled:
            self.registered.add(usage)
        else:
            self.registered.remove(usage)

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) != b"windows_generic_MSG":
            return False, 0
        msg = W.MSG.from_address(int(message))
        if msg.message != WM_INPUT or msg.hWnd != self.hwnd:
            return False, 0
        header_size = C.sizeof(RawInputHeader)
        size = W.UINT(C.sizeof(self.buffer))
        count = self.user.GetRawInputData(msg.lParam, 0x10000003, self.buffer, C.byref(size), header_size)
        if header_size <= count <= C.sizeof(self.buffer):
            header = RawInputHeader.from_buffer(self.buffer)
            if header.kind == 0 and 2 in self.registered and count >= header_size + C.sizeof(RawMouse):
                mouse = RawMouse.from_buffer(self.buffer, header_size)
                relative = not mouse.flags & 1
                self.wheel.mouse(mouse.x if relative else 0, mouse.y if relative else 0, mouse.buttons & 0xFFFF)
            elif header.kind == 1 and 6 in self.registered and count >= header_size + C.sizeof(RawKeyboard):
                key = RawKeyboard.from_buffer(self.buffer, header_size)
                self.wheel.key(key.vk, key.flags, key.scan)
        return False, 0


class CategoryWheel:
    def __init__(self, app, hwnd, api, sender, settings, can_open, on_selection, report):
        self.app, self.api, self.sender, self.settings = app, api, sender, settings
        self.can_open, self.on_selection, self.report = can_open, on_selection, report
        self.overlay = None
        self.target = None
        self.alt_down = False
        self.chord_keys = set()
        self.pressed_at = 0.0
        self.timer = QTimer()
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.poll)
        user = api.user
        user.GetClientRect.argtypes, user.GetClientRect.restype = [W.HWND, C.POINTER(W.RECT)], W.BOOL
        user.ClientToScreen.argtypes, user.ClientToScreen.restype = [W.HWND, C.POINTER(W.POINT)], W.BOOL
        user.MonitorFromWindow.argtypes, user.MonitorFromWindow.restype = [W.HWND, W.DWORD], W.HANDLE
        user.GetMonitorInfoW.argtypes, user.GetMonitorInfoW.restype = [W.HANDLE, C.POINTER(MonitorInfo)], W.BOOL
        self.input = WheelInput(self, hwnd)
        self.input.register(6, True)
        app.installNativeEventFilter(self.input)

    @property
    def visible(self):
        return self.overlay is not None and self.overlay.isVisible()

    def key(self, vk, flags, scan):
        if vk == 0xFF:
            return
        down = not flags & KEY_UP
        left_alt = vk == VK_LEFT_ALT or (vk == VK_ALT and not flags & KEY_EXTENDED)
        if not left_alt:
            if vk in CHORD_KEYS:
                key_id = (vk, flags & 6, scan)
                if down:
                    self.chord_keys.add(key_id)
                else:
                    self.chord_keys.discard(key_id)
            if down and self.target is not None:
                self.finish()
            return
        if self.alt_down == down:
            return
        self.alt_down = down
        if down:
            if not self.chord_keys and self.can_open():
                self.target = self.api.target()
                if self.target is not None:
                    self.pressed_at = time.monotonic()
                    self.timer.start()
        elif self.target is not None:
            self.finish(confirm=self.api.is_foreground(self.target))

    def poll(self):
        if self.target is None or not self.can_open() or not self.api.is_foreground(self.target):
            self.finish()
        elif not self.visible and time.monotonic() - self.pressed_at >= 2:
            self.show()

    def show(self):
        with self.sender.lock:
            messages = self.sender.messages
            names = {category["id"]: category["name"] for category in messages.categories}
            active = messages.wheel_categories
            options = tuple((cid, names[cid], bool(messages.category_count(cid)))
                            for cid in self.settings.categories if cid in names)
        if not options and not active:
            self.finish()
            return
        if self.overlay is None:
            self.overlay = WheelOverlay()
        if not self.center_on_target():
            self.finish()
            return
        try:
            self.input.register(2, True)
        except OSError as exc:
            self.report(f"已忽略：轮盘无法读取鼠标输入（{exc}）。")
            self.finish()
            return
        self.overlay.draft = WheelDraft(options, active, names)
        self.overlay.show()
        if not self.api.is_foreground(self.target):
            self.finish()

    def center_on_target(self):
        hwnd, _ = self.target
        user = self.api.user
        rect, origin, monitor = W.RECT(), W.POINT(), MonitorInfo()
        monitor.size = C.sizeof(monitor)
        if not (user.GetClientRect(hwnd, C.byref(rect))
                and user.ClientToScreen(hwnd, C.byref(origin))
                and user.GetMonitorInfoW(user.MonitorFromWindow(hwnd, 2), C.byref(monitor))):
            return False
        # Qt retains each Windows screen origin and scales its dimensions.
        screen = next((screen for screen in self.app.screens()
                       if (screen.geometry().x(), screen.geometry().y())
                       == (monitor.monitor.left, monitor.monitor.top)), None)
        if screen is None:
            return False
        self.overlay.winId()
        self.overlay.windowHandle().setScreen(screen)
        scale = screen.devicePixelRatio()
        area = screen.geometry()
        x = (origin.x + (rect.right - rect.left) / 2 - monitor.monitor.left) / scale
        y = (origin.y + (rect.bottom - rect.top) / 2 - monitor.monitor.top) / scale
        self.overlay.move(round(area.x() + x - self.overlay.SIZE / 2),
                          round(area.y() + y - self.overlay.SIZE / 2))
        return True

    def mouse(self, dx, dy, buttons):
        if not self.visible:
            return
        if not self.api.is_foreground(self.target):
            self.finish()
            return
        draft = self.overlay.draft
        previous = (draft.hover, tuple(draft.order))
        if dx or dy:
            draft.move(dx, dy)
        draft.click(buttons)
        if previous != (draft.hover, tuple(draft.order)):
            self.overlay.update()

    def finish(self, *, confirm=False):
        self.timer.stop()
        self.target = None
        if not self.visible:
            return
        selection = self.overlay.draft.selection() if confirm and self.can_open() else None
        self.overlay.hide()
        self.overlay.draft = None
        self.unregister(2)
        if selection is not None:
            self.on_selection(selection)

    def unregister(self, usage):
        try:
            self.input.register(usage, False)
        except OSError:
            logger.exception("could not unregister wheel Raw Input usage=%s", usage)

    def close(self):
        self.finish()
        self.app.removeNativeEventFilter(self.input)
        self.unregister(2)
        self.unregister(6)
        if self.overlay is not None:
            self.overlay.deleteLater()

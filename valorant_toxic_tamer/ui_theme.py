"""Shared, dependency-free Qt widget styling for the desktop UI."""
import re

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabBar, QVBoxLayout, QWidget)


RED = "#ff4655"
TEXT = "#edf2f6"
MUTED = "#96a4b2"
STYLE = """
QWidget { color: #edf2f6; font: 11pt 'Microsoft YaHei UI'; }
QMainWindow, QDialog, QMessageBox { background: #0c141d; }
QLabel { background: transparent; }
QLabel#brand { font-size: 19pt; font-weight: 700; }
QLabel#section { font-size: 14pt; font-weight: 700; border-left: 3px solid #ff4655; padding-left: 12px; }
QLabel#muted { color: #96a4b2; }
QLabel#preview { font-size: 19pt; font-weight: 600; }
QLabel#progress { font-size: 28pt; font-weight: 700; }
QLabel#ready { color: #68ded2; font-weight: 600; }
QLabel#keycap { border: 1px solid #536171; padding: 6px 12px; font-weight: 600; }
QFrame#separator { background: #2b3947; border: 0; max-height: 1px; }
QTabWidget::pane { border: 0; background: transparent; }
QListWidget { background: transparent; border: 0; outline: 0; }
QListWidget::item { border: 0; }
QComboBox, QLineEdit { background: transparent; border: 0; selection-background-color: #73303e; }
QCheckBox { spacing: 10px; background: transparent; padding: 5px 0; }
QCheckBox::indicator { width: 18px; height: 18px; }
QCheckBox:focus { outline: 1px solid #96a4b2; }
QPushButton { background: #23313f; border: 1px solid #4a5d6e; padding: 9px 18px; min-height: 22px; }
QPushButton:hover { background: #304353; }
QMenu { background: #17222e; border: 1px solid #415263; padding: 5px; }
QMenu::item { padding: 9px 24px; }
QMenu::item:selected { background: #303e4e; border-left: 2px solid #ff4655; }
QMenu::separator { height: 1px; background: #344454; margin: 5px 8px; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: 0; }
QScrollBar:vertical { background: #121c26; width: 7px; margin: 2px 0; }
QScrollBar::handle:vertical { background: #435364; min-height: 28px; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { background: #202d3b; color: #edf2f6; border: 1px solid #526275; padding: 6px; }
"""


def style_for_font_size(font_size):
    return re.sub(r"(\d+)pt", lambda match: f"{int(match[1]) + font_size - 11}pt", STYLE)


def cut_path(rect, cut=8):
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(x + cut, y), QPointF(x + w, y),
        QPointF(x + w, y + h - cut), QPointF(x + w - cut, y + h),
        QPointF(x, y + h), QPointF(x, y + cut)]))
    path.closeSubpath()
    return path


def paint_button(button):
    p = QPainter(button)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    primary = bool(button.property("primary"))
    enabled = button.isEnabled()
    hovered = button.underMouse() and enabled
    top, bottom = ("#ff5663", "#ec3546") if primary else ("#25323f", "#192530")
    border = "#ff6975" if primary else "#4a5d6e"
    if hovered:
        top, bottom = ("#ff6c78", "#fa4658") if primary else ("#334453", "#233340")
    if button.isDown():
        top = bottom = "#cb3041" if primary else "#14202b"
    if not enabled:
        top = bottom = "#16212b"
        border = "#2a3845"
    elif button.hasFocus():
        border = "#ffc1c7" if primary else RED
    gradient = QLinearGradient(0, 0, 0, button.height())
    gradient.setColorAt(0, QColor(top))
    gradient.setColorAt(1, QColor(bottom))
    p.setPen(QPen(QColor(border), 1.2))
    p.setBrush(gradient)
    p.drawPath(cut_path(QRectF(button.rect()).adjusted(0.8, 0.8, -0.8, -0.8)))
    p.setPen(QColor(TEXT if enabled else "#62717f"))
    p.setFont(button.font())
    update_icon = bool(button.property("updateIcon"))
    icon_width = 32 if update_icon else 22 if not button.icon().isNull() else 0
    text_width = button.fontMetrics().horizontalAdvance(button.text().replace("&", ""))
    start = (button.width() - text_width - icon_width) / 2
    if update_icon:
        p.save()
        p.translate(start + 10, button.height() / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#22ffffff" if enabled else "#2262717f"))
        p.drawEllipse(QRectF(-13, -13, 26, 26))
        p.rotate(button.angle)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(TEXT if enabled or button.animation.isActive() else "#62717f"),
                      1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawArc(QRectF(-6, -6, 12, 12), 40 * 16, 280 * 16)
        p.drawPolyline(QPolygonF([QPointF(1.5, -4), QPointF(4.6, -3.8), QPointF(4.9, -7)]))
        p.restore()
    elif icon_width:
        mode = button.icon().Mode.Normal if enabled else button.icon().Mode.Disabled
        button.icon().paint(p, int(start), (button.height() - 16) // 2, 16, 16,
                            Qt.AlignmentFlag.AlignCenter, mode)
    p.drawText(QRectF(start + icon_width, 0, text_width, button.height()),
               Qt.AlignmentFlag.AlignCenter, button.text().replace("&", ""))


class CutButton(QPushButton):
    def __init__(self, text, parent=None, *, primary=False):
        super().__init__(text, parent)
        self.setProperty("primary", primary)
        self.setMinimumHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoDefault(False)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) +
                     (60 if not self.icon().isNull() else 38), max(42, self.fontMetrics().height() + 20))

    def paintEvent(self, event):
        paint_button(self)


class UpdateButton(CutButton):
    def __init__(self, parent=None):
        super().__init__("检查更新", parent, primary=True)
        self.setProperty("updateIcon", True)
        self.setAccessibleName("检查更新")
        self.setMinimumHeight(48)
        self.angle = 0
        self.animation = QTimer(self)
        self.animation.setInterval(40)
        self.animation.timeout.connect(self._advance)

    def _advance(self):
        self.angle = (self.angle + 12) % 360
        self.update()

    def set_busy(self, busy):
        if busy:
            self.animation.start()
        else:
            self.animation.stop()
            self.angle = 0
        self.update()

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 74,
                     max(48, self.fontMetrics().height() + 24))


class TacticalCheckBox(QCheckBox):
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = (self.height() - 18) / 2
        p.setPen(QPen(QColor(RED if self.hasFocus() else "#68ded2" if self.isChecked() else "#8595a5"), 1.3))
        p.setBrush(QColor("#121d27"))
        p.drawRect(QRectF(1, y, 18, 18))
        if self.isChecked():
            p.setPen(QPen(QColor("#68ded2"), 2))
            p.drawPolyline(QPolygonF([QPointF(4, y + 9), QPointF(8, y + 13), QPointF(16, y + 4)]))
        p.setPen(QColor(TEXT if self.isEnabled() else MUTED))
        p.setFont(self.font())
        p.drawText(QRectF(30, 0, self.width() - 30, self.height()),
                   Qt.AlignmentFlag.AlignVCenter, self.text())


class _ButtonSkin(QObject):
    """Keep QMessageBox's standard buttons and return codes intact."""
    def eventFilter(self, button, event):
        if event.type() == QEvent.Type.Paint:
            paint_button(button)
            return True
        return super().eventFilter(button, event)


def style_message_box(dialog, primary=None):
    parent = dialog.parentWidget()
    dialog.setStyleSheet(parent.styleSheet() if parent else STYLE)
    dialog.setMinimumWidth(420)
    dialog.setTextFormat(Qt.TextFormat.PlainText)
    for button in dialog.buttons():
        button.setProperty("primary", dialog.standardButton(button) == primary)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAttribute(Qt.WidgetAttribute.WA_Hover)
        skin = _ButtonSkin(button)
        button.installEventFilter(skin)


class Panel(QWidget):
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0, QColor("#17222d"))
        gradient.setColorAt(1, QColor("#101a24"))
        p.setBrush(gradient)
        p.setPen(QPen(QColor("#344453"), 1))
        p.drawPath(cut_path(QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6), 12))


class CutComboBox(QComboBox):
    def __init__(self, parent=None, *, wheel_changes=True):
        super().__init__(parent)
        self.wheel_changes = wheel_changes
        self.opened = False
        self.setMinimumHeight(42)
        self.setMinimumWidth(130)
        self.setMaximumWidth(270)
        self.setMaxVisibleItems(8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view().setStyleSheet("""
            QListView { background: #17222e; color: #edf2f6; border: 1px solid #506173;
                        outline: 0; padding: 3px; }
            QListView::item { min-height: 34px; padding-left: 14px; border-left: 3px solid transparent; }
            QListView::item:hover { background: #2b3b4b; }
            QListView::item:selected { background: #472a36; border-left: 3px solid #ff4655; }
        """)

    def wheelEvent(self, event):
        if self.wheel_changes:
            super().wheelEvent(event)
        else:
            event.ignore()

    def showPopup(self):
        self.opened = True
        self.update()
        super().showPopup()

    def hidePopup(self):
        self.opened = False
        super().hidePopup()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.hasFocus() or self.opened
        p.setPen(QPen(QColor(RED if active else "#536575"), 1.2))
        p.setBrush(QColor("#182530" if self.isEnabled() else "#14202a"))
        p.drawPath(cut_path(QRectF(self.rect()).adjusted(0.8, 0.8, -0.8, -0.8)))
        p.setPen(QColor(TEXT if self.isEnabled() else MUTED))
        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.drawText(QRectF(18, 0, self.width() - 62, self.height()),
                   Qt.AlignmentFlag.AlignVCenter, self.currentText())
        p.setPen(QPen(QColor("#536575"), 1))
        p.drawLine(self.width() - 42, 11, self.width() - 42, self.height() - 11)
        p.setPen(QPen(QColor(RED if active else TEXT), 1.6))
        x, y = self.width() - 21, self.height() / 2
        sign = -1 if self.opened else 1
        p.drawPolyline(QPolygonF([QPointF(x - 5, y - 2 * sign),
                                  QPointF(x, y + 3 * sign), QPointF(x + 5, y - 2 * sign)]))


class CutLineEdit(QLineEdit):
    def __init__(self, parent=None, *, suffix=""):
        super().__init__(parent)
        self.suffix = suffix
        self.setMinimumHeight(42)
        self.setTextMargins(16, 0, 48 if suffix else 16, 0)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(RED if self.hasFocus() else "#536575"), 1.2))
        p.setBrush(QColor("#182530"))
        p.drawPath(cut_path(QRectF(self.rect()).adjusted(0.8, 0.8, -0.8, -0.8)))
        if self.suffix:
            p.setPen(QColor("#536575"))
            p.drawLine(self.width() - 42, 11, self.width() - 42, self.height() - 11)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(self.width() - 41, 0, 40, self.height()),
                       Qt.AlignmentFlag.AlignCenter, self.suffix)
        p.end()
        super().paintEvent(event)


class CutTabBar(QTabBar):
    def tabSizeHint(self, index):
        return QSize(max(150, self.fontMetrics().horizontalAdvance(self.tabText(index)) + 44),
                     max(48, self.fontMetrics().height() + 20))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i in range(self.count()):
            rect = QRectF(self.tabRect(i)).adjusted(1, 2, -5, -3)
            active = i == self.currentIndex()
            p.setPen(QPen(QColor(RED if active else "#344453"), 1))
            p.setBrush(QColor(RED if active else "#192530"))
            p.drawPath(cut_path(rect, 16))
            p.setPen(QColor(TEXT))
            font = QFont(self.font())
            font.setWeight(QFont.Weight.DemiBold)
            p.setFont(font)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.tabText(i))
            if active and self.hasFocus():
                p.setPen(QPen(QColor("#ffc1c7"), 2))
                p.drawLine(int(rect.left() + 22), int(rect.bottom() - 6),
                           int(rect.right() - 22), int(rect.bottom() - 6))


class MessageDialog(QDialog):
    def __init__(self, parent, title, text="", row=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowIcon(parent.windowIcon())
        self.setStyleSheet(parent.styleSheet())
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(16)
        heading = QLabel(title)
        heading.setObjectName("section")
        layout.addWidget(heading)
        if row is not None:
            number = QLabel(f"第 {row + 1:02d} 条")
            number.setObjectName("muted")
            layout.addWidget(number)
        layout.addWidget(QLabel("消息内容（单行）"))
        self.input = CutLineEdit()
        self.input.setAccessibleName("消息内容（单行）")
        self.input.setText(text)
        layout.addWidget(self.input)
        hint = QLabel("保存后自动更新列表，循环从第一条开始。" if row is not None
                      else "添加后加入列表末尾，循环从第一条开始。")
        hint.setObjectName("muted")
        layout.addWidget(hint)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = CutButton("取消")
        cancel.clicked.connect(self.reject)
        save = CutButton("保存" if row is not None else "添加", primary=True)
        save.setDefault(True)
        save.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addLayout(actions)
        self.input.returnPressed.connect(self.accept)
        self.input.setFocus()
        self.input.selectAll()

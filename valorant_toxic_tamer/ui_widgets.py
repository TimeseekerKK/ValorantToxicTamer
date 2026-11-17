"""Shared UI primitives and list rendering; no persistence or page workflows."""
from collections import OrderedDict

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPen
from PySide6.QtWidgets import (QFrame, QLabel, QListWidget, QSizePolicy, QStyledItemDelegate,
                               QStyle, QStyleOptionViewItem)

from .ui_theme import MUTED, RED, TEXT, CutButton


def label(text, name=None, wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if name:
        widget.setObjectName(name)
    return widget


def separator():
    line = QFrame()
    line.setObjectName("separator")
    line.setFixedHeight(1)
    return line


class CategoryOrderDelegate(QStyledItemDelegate):
    ORDER_ROLE = Qt.ItemDataRole.UserRole + 1

    def paint(self, painter, option, index):
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        order = index.data(self.ORDER_ROLE)
        checked = styled.checkState == Qt.CheckState.Checked
        # Keep the standard layout and hit target, replacing only the check mark.
        if checked:
            styled.checkState = Qt.CheckState.Unchecked
        style = styled.widget.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)
        if checked and order is not None:
            rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, styled, styled.widget)
            painter.save()
            painter.setPen(QPen(QColor("#68ded2" if styled.state & QStyle.StateFlag.State_Enabled else MUTED), 1))
            painter.setBrush(QColor("#203b3a"))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            font = QFont(styled.font)
            font.setBold(True)
            text = str(order)
            while font.pixelSize() > 8 and QFontMetrics(font).horizontalAdvance(text) > rect.width() - 4:
                font.setPixelSize(font.pixelSize() - 1)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            painter.restore()


class MessageDelegate(QStyledItemDelegate):
    def __init__(self, page):
        super().__init__(page.list_widget)
        self.page = page
        self._column_key = None
        self._column_widths = None
        self._sizes = OrderedDict()

    def column_widths(self):
        digits = max(2, len(str(self.page.list_widget.count())))
        key = (self.page.host.config.value["font_size"], self.page.list_widget.logicalDpiX(), digits)
        if key == self._column_key:
            return self._column_widths
        metrics = self.page.list_widget.fontMetrics()
        number = max(36, max(metrics.horizontalAdvance(str(i) * digits) for i in range(10)))
        upcoming_font = QFont(self.page.list_widget.font())
        upcoming_font.setPixelSize(max(8, upcoming_font.pixelSize() - 1))
        upcoming = max(60, QFontMetrics(upcoming_font).horizontalAdvance("下一条"))
        self._column_key = key
        self._column_widths = number, upcoming
        return self._column_widths

    def sizeHint(self, option, index):
        number, upcoming = self.column_widths()
        reserved = number + upcoming + 40
        width = max(1, self.page.list_widget.viewport().width() - reserved)
        text = index.data(Qt.ItemDataRole.UserRole) or ""
        key = (text, self._column_key, width, reserved)
        cached = self._sizes.get(key)
        if cached is not None:
            self._sizes.move_to_end(key)
            return cached
        rect = self.page.list_widget.fontMetrics().boundingRect(
            QRect(0, 0, width, 100000), Qt.TextFlag.TextWordWrap, text)
        size = QSize(width + reserved, max(42, rect.height() + 18))
        self._sizes[key] = size
        if len(self._sizes) > 25000:
            self._sizes.popitem(last=False)
        return size

    def paint(self, painter, option, index):
        painter.save()
        painter.setClipRect(option.rect)
        rect = option.rect
        number_width, upcoming_width = self.column_widths()
        upcoming = index.row() == self.page.next_index
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(rect, QColor("#2b3e50"))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(rect, QColor("#1e2d3b"))
        if upcoming:
            painter.fillRect(QRect(rect.left(), rect.top() + 1, 3, rect.height() - 2), QColor(RED))
        painter.setPen(QColor("#30404f"))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.setFont(option.font)
        painter.setPen(QColor(MUTED))
        painter.drawText(QRect(rect.left() + 16, rect.top(), number_width, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter, f"{index.row() + 1:02d}")
        painter.setPen(QColor(TEXT))
        painter.drawText(QRect(rect.left() + number_width + 24, rect.top() + 9,
                               rect.width() - number_width - upcoming_width - 40, rect.height() - 18),
                         Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignVCenter,
                         index.data(Qt.ItemDataRole.UserRole) or "")
        if upcoming:
            font = QFont(option.font)
            font.setPixelSize(max(8, font.pixelSize() - 1))
            painter.setFont(font)
            painter.setPen(QColor("#ff8290"))
            badge = QRect(rect.right() - upcoming_width - 8, rect.center().y() - 12, upcoming_width, 24)
            painter.drawRect(badge)
            painter.drawText(badge,
                             Qt.AlignmentFlag.AlignCenter, "下一条")
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(QPen(QColor("#6c8296"), 1, Qt.PenStyle.DashLine))
            painter.drawRect(rect.adjusted(5, 4, -5, -4))
        painter.restore()


class MessageList(QListWidget):
    def __init__(self):
        super().__init__()
        self.layout_timer = QTimer(self)
        self.layout_timer.setSingleShot(True)
        self.layout_timer.setInterval(60)
        self.layout_timer.timeout.connect(self.doItemsLayout)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.layout_timer.start()


class WrappingLabel(QLabel):
    """Grow inside the scroll area instead of clipping wrapped text."""
    def __init__(self, text="", *, minimum_lines=1):
        super().__init__(text)
        self.minimum_lines = minimum_lines
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def update_height(self):
        # QLabel.heightForWidth() includes the old minimum; allow shorter text to shrink.
        self.setMinimumHeight(0)
        self.setMinimumHeight(max(self.fontMetrics().lineSpacing() * self.minimum_lines,
                                  self.heightForWidth(max(1, self.width()))))

    def setText(self, text):
        if text != self.text():
            super().setText(text)
            self.update_height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_height()


def action_button(parent, text, action, *, primary=False, icon=None):
    button = CutButton(text, primary=primary)
    if icon is not None:
        button.setIcon(parent.style().standardIcon(icon))
    button.clicked.connect(action)
    return button

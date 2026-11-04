from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygon
from PySide6.QtCore import QPoint
from .ui_theme import STYLE
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def app_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#101b29"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#ff5364"))
    painter.setBrush(QColor("#ff5364"))
    painter.drawPolygon(QPolygon([QPoint(12, 13), QPoint(31, 40), QPoint(52, 13),
                                  QPoint(52, 34), QPoint(32, 54), QPoint(12, 34)]))
    painter.end()
    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    def __init__(self, window, quit_callback):
        super().__init__(app_icon(), window)
        self.setToolTip("ValorantToxicTamer")
        self.menu = QMenu(window)
        self.menu.setStyleSheet(STYLE)
        for title, page in (("显示主窗口", 0), ("消息管理", 0), ("设置", 1), ("运行状态", 0)):
            action = self.menu.addAction(title)
            action.triggered.connect(lambda checked=False, p=page: window.reveal(p))
        self.menu.addSeparator()
        self.menu.addAction("退出程序", quit_callback)
        self.setContextMenu(self.menu)
        self.activated.connect(lambda reason: window.reveal(0)
                               if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.show()

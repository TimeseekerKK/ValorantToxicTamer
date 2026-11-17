"""Main window: page composition, shared status and application lifecycle."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QTabWidget, QVBoxLayout, QWidget)

from .app_version import VERSION
from .tray import app_icon
from .update_controller import UpdateController
from .ui_management import ManagementPage
from .ui_settings import SettingsPage
from .ui_theme import RED, CutTabBar, style_for_font_size, style_message_box
from .ui_widgets import label, separator


class MainWindow(QMainWindow):
    def __init__(self, messages, config, sender, save_settings):
        super().__init__()
        self.messages, self.config, self.sender = messages, config, sender
        self.messages.set_mode(config.value["category_mode"])
        self.save_settings = save_settings
        self.settings_loaded = False
        self.settings = None
        self.closing = False
        self.updater = UpdateController(self)
        self.setWindowTitle(f"ValorantToxicTamer · V{VERSION}")
        self.setWindowIcon(app_icon())
        self.resize(1195, 791)
        self.setMinimumSize(840, 638)
        self.setStyleSheet(style_for_font_size(config.value["font_size"]))
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 18, 22, 14)
        layout.setSpacing(14)
        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(self.windowIcon().pixmap(38, 38))
        header.addWidget(icon)
        header.addSpacing(8)
        header.addWidget(label("ValorantToxicTamer", "brand"))
        header.addWidget(label(f"V{VERSION}", "muted"))
        header.addStretch()
        layout.addLayout(header)
        layout.addWidget(separator())
        self.tabs = QTabWidget()
        self.tabs.setTabBar(CutTabBar())
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs, 1)
        self.management = ManagementPage(self)
        self.tabs.addTab(self.management, "消息管理")
        self.settings_placeholder = QWidget()
        self.tabs.addTab(self.settings_placeholder, "设置")
        self.tabs.currentChanged.connect(self._page_changed)
        layout.addWidget(separator())
        self.result_label = label("就绪 · 请添加消息，然后在游戏前台使用快捷键。", wrap=True)
        layout.addWidget(self.result_label)
        layout.addWidget(label("发送前请关闭游戏聊天框，并松开修饰键。程序无法确认聊天框状态或服务器送达。",
                               "muted", True))
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh_status)
        self.management.reload_messages()
        self.apply_font_size()
        if self.messages.count:
            self.result_label.setText("就绪 · 在游戏前台使用快捷键，按顺序输入下一条消息。")
        if self.updater.preferences_error:
            self.result_label.setText("更新设置无法读取，暂用正式版渠道；可在设置页恢复。消息管理和快捷发送仍可使用。")

    def _page_changed(self, page):
        if page == 1:
            self.ensure_settings()

    def ensure_settings(self):
        if self.settings_loaded:
            return
        self.settings = SettingsPage(self)
        current = self.tabs.currentIndex()
        self.tabs.blockSignals(True)
        self.tabs.removeTab(1)
        self.tabs.insertTab(1, self.settings, "设置")
        self.tabs.setCurrentIndex(current)
        self.tabs.blockSignals(False)
        self.settings_placeholder.deleteLater()
        self.settings_loaded = True
        self.settings.load_settings()
        self.management.update_actions()

    def apply_font_size(self):
        self.setStyleSheet(style_for_font_size(self.config.value["font_size"]))
        self.management.next_label.update_height()
        self.management.progress_label.update_height()
        self.management.list_widget.doItemsLayout()

    def set_hotkey_status(self, status):
        self.management.keys_label.setText(f"队伍：{status['team']}\n全体：{status['all']}")
        self.management.team_hint.setText(self.config.value["team_hotkey"])
        self.management.all_hint.setText(self.config.value["all_hotkey"])

    def refresh_status(self):
        with self.sender.lock:
            cid, count, index, next_row, current = self.messages.current_state()
            remaining = max(0, self.sender.ready_at - self.sender.clock())
            busy = self.sender.busy
            state = ("正在输入" if busy else f"冷却 {remaining:.1f}s" if remaining
                     else "就绪" if count else "当前发送范围为空")
            current = current or "暂无消息"
        position = index + 1 if count else 0
        category = self.messages.category_name(cid) if cid else "未选择有效消息"
        self.management.state_label.setText(f"● {state}  |  {position} / {count}\n{category}")
        self.management.update_send_order()
        self.management.progress_label.setText(f'<span style="color:{RED}">{position:02d}</span>'
                                    f' <span style="font-size:{self.config.value["font_size"] + 9}px">/ {count:02d}</span>')
        if self.management.next_label.text() != current:
            self.management.next_label.setText(current)
            self.management.next_label.setToolTip(current)
            self.management.preview_scroll.verticalScrollBar().setValue(0)
        next_index = next_row if count else -1
        if self.management.next_index != next_index:
            self.management.next_index = next_index
            self.management.list_widget.viewport().update()
        self.management.update_actions()

        if self.isVisible() and (busy or remaining > 0):
            if not self.timer.isActive():
                self.timer.start()
        else:
            self.timer.stop()

    def report(self, message):
        self.result_label.setText(message)
        if self.isVisible():
            self.refresh_status()

    def error(self, error):
        dialog = QMessageBox(QMessageBox.Icon.Warning, "操作未完成", str(error),
                             QMessageBox.StandardButton.Ok, self)
        dialog.button(QMessageBox.StandardButton.Ok).setText("知道了")
        style_message_box(dialog, QMessageBox.StandardButton.Ok)
        dialog.exec()
        dialog.deleteLater()

    def information(self, title, text):
        dialog = QMessageBox(QMessageBox.Icon.Information, title, text,
                             QMessageBox.StandardButton.Ok, self)
        dialog.button(QMessageBox.StandardButton.Ok).setText("知道了")
        style_message_box(dialog, QMessageBox.StandardButton.Ok)
        dialog.exec()
        dialog.deleteLater()

    def reveal(self, page=0):
        self.tabs.setCurrentIndex(page)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        self.hide()
        event.ignore()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_status()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def begin_shutdown(self):
        self.closing = True
        self.timer.stop()
        self.management.begin_shutdown()
        self.updater.begin_shutdown()

    def shutdown(self):
        self.begin_shutdown()
        self.management.shutdown()
        self.updater.shutdown()

    def reload_messages(self, row=None):
        self.management.reload_messages(row)

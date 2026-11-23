"""Main window: page composition, shared status and application lifecycle."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QTabWidget, QVBoxLayout, QWidget)

from .app_version import VERSION
from .tray import app_icon
from .update_controller import UpdateController
from .ui_management import ManagementPage
from .ui_settings import SettingsPage
from .ui_theme import CutTabBar, style_for_font_size, style_message_box
from .ui_widgets import label, separator


class MainWindow(QMainWindow):
    def __init__(self, messages, config, sender, save_settings, *, wheel_settings=None, save_wheel_settings=None):
        super().__init__()
        self.messages, self.config, self.sender = messages, config, sender
        self.messages.set_mode(config.value["category_mode"])
        self.save_settings = save_settings
        self.wheel_settings = wheel_settings
        self.save_wheel_settings = save_wheel_settings
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
        layout.setContentsMargins(18, 8, 18, 10)
        layout.setSpacing(8)
        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(self.windowIcon().pixmap(30, 30))
        header.addWidget(icon)
        header.addSpacing(8)
        header.addWidget(label("ValorantToxicTamer", "brand"))
        header.addWidget(label(f"V{VERSION}", "muted"))
        header.addStretch()
        self.navigation = CutTabBar()
        self.navigation.addTab("消息管理")
        self.navigation.addTab("设置")
        header.addWidget(self.navigation)
        layout.addLayout(header)
        layout.addWidget(separator())
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().hide()
        layout.addWidget(self.tabs, 1)
        self.management = ManagementPage(self)
        self.tabs.addTab(self.management, "消息管理")
        self.settings_placeholder = QWidget()
        self.tabs.addTab(self.settings_placeholder, "设置")
        self.tabs.currentChanged.connect(self._page_changed)
        self.tabs.currentChanged.connect(self.navigation.setCurrentIndex)
        self.navigation.currentChanged.connect(self.tabs.setCurrentIndex)
        layout.addWidget(separator())
        self.result_label = label("请添加消息，然后在游戏前台使用快捷键。", "muted", True)
        layout.addWidget(self.result_label)
        self.result_label.setToolTip("发送前请关闭游戏聊天框，并松开修饰键。程序无法确认聊天框状态或服务器送达。")
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh_status)
        self.background_timer = QTimer(self)
        self.background_timer.setSingleShot(True)
        self.background_timer.setInterval(15000)
        self.background_timer.timeout.connect(self._release_background_resources)
        self.management.reload_messages()
        self.apply_font_size()
        if self.messages.count:
            self.result_label.setText("游戏前台使用快捷键 · 发送前关闭聊天框并松开修饰键")
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
        self.management.resize_progress()
        self.management.resize_category_list()
        self.management.list_widget.doItemsLayout()

    def set_hotkey_status(self, status):
        self.management.team_hint.setText(self.config.value["team_hotkey"])
        self.management.all_hint.setText(self.config.value["all_hotkey"])
        details = f"队伍：{status['team']}\n全体：{status['all']}"
        for hint, channel in ((self.management.team_hint, "team"), (self.management.all_hint, "all")):
            hint.setToolTip(status[channel])
        warnings = [name for channel, name in (("team", "队伍"), ("all", "全体"))
                    if "已注册" not in status[channel]]
        self.management.keys_label.setText(f"{' / '.join(warnings)}快捷键异常" if warnings else "")
        self.management.keys_label.setVisible(bool(warnings))
        self.management.keys_label.setAccessibleDescription(details)
        self.management.keys_label.setToolTip(details)

    def refresh_status(self):
        with self.sender.lock:
            cid, count, index, next_row, current = self.messages.current_state()
            remaining = max(0, self.sender.ready_at - self.sender.clock())
            busy = self.sender.busy
            paused = self.sender.paused
            state = ("已暂停" if paused else "正在输入" if busy else f"冷却 {remaining:.1f}s" if remaining
                     else "就绪" if count else "轮盘类别已清空或删除" if self.messages.wheel_categories
                     else "当前发送范围为空")
            current = current or "暂无消息"
        position = index + 1 if count else 0
        category = self.messages.category_name(cid) if cid else "发送进度"
        self.management.state_label.setText(f"● {state}")
        state_style = "color: #e9bd75;" if paused else "color: #68ded2;" if count else "color: #96a4b2;"
        if self.management.state_label.styleSheet() != state_style:
            self.management.state_label.setStyleSheet(state_style)
        self.management.pause_button.setText("继续发送" if paused else "暂停发送")
        self.management.update_send_order()
        self.management.active_category_label.set_full_text(category)
        progress = f"第 {position} / {count} 条" if count else "00 / 00"
        if self.management.progress_label.text() != progress:
            self.management.progress_label.setText(progress)
            self.management.resize_progress()
        next_index = next_row if count else -1
        message_changed = self.management.next_label.text() != current
        if message_changed:
            self.management.next_label.setText(current)
            self.management.next_label.setToolTip(current)
        if message_changed or self.management.next_index != next_index:
            self.management.preview_scroll.verticalScrollBar().setValue(0)
        if self.management.next_index != next_index:
            self.management.next_index = next_index
            self.management.list_widget.viewport().update()
        self.management.update_actions()

        if self.isVisible() and not self.isMinimized() and (busy or remaining > 0):
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
        self.background_timer.stop()
        super().showEvent(event)
        self.management.resume_messages()
        self.refresh_status()

    def hideEvent(self, event):
        self.timer.stop()
        if not self.closing:
            self.background_timer.start()
        super().hideEvent(event)

    def _release_background_resources(self):
        if self.closing or (self.isVisible() and not self.isMinimized()):
            return
        # Dialogs and workers may still reference the live list. Retry after
        # they finish instead of interfering with imports or update prompts.
        if (self.management.import_worker is not None or self.updater.busy
                or QApplication.activeModalWidget() is not None
                or QApplication.activePopupWidget() is not None):
            self.background_timer.start()
            return
        self.management.suspend_messages()

    def begin_shutdown(self):
        self.closing = True
        self.timer.stop()
        self.background_timer.stop()
        self.management.begin_shutdown()
        self.updater.begin_shutdown()

    def shutdown(self):
        self.begin_shutdown()
        self.management.shutdown()
        self.updater.shutdown()

    def reload_messages(self, row=None):
        self.management.reload_messages(row)

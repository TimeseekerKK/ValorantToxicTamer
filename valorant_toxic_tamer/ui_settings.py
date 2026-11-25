"""Lazily constructed settings page and its validation/save workflow."""
from PySide6.QtCore import QSignalBlocker, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QProgressBar, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from .app_version import VERSION
from .config_manager import DEFAULT_CONFIG, FONT_SIZES, HOTKEYS
from .message_manager import CATEGORY_MODES
from .update_settings import RELEASES_PAGE, UPDATE_CHANNELS
from .ui_theme import (CutButton, CutComboBox, CutLineEdit, Panel,
                       TacticalCheckBox, UpdateButton)
from .ui_widgets import action_button, label, separator
from .wheel_settings import WHEEL_LIMIT


class SettingsPage(QWidget):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(8)
        scroll = QScrollArea()
        self.form_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        columns = QHBoxLayout(body)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(12)
        left = Panel()
        controls = QVBoxLayout(left)
        controls.setContentsMargins(16, 14, 16, 14)
        controls.setSpacing(8)
        heading = QHBoxLayout()
        heading.addWidget(label("发送设置", "section"))
        heading.addWidget(label("手动保存", "muted"))
        heading.addStretch()
        controls.addLayout(heading)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.team_key, self.all_key = CutComboBox(), CutComboBox()
        for box in (self.team_key, self.all_key):
            box.addItems(HOTKEYS)
        self.team_key.setAccessibleName("队伍聊天快捷键")
        self.all_key.setAccessibleName("全体聊天快捷键")
        self.cooldown = CutLineEdit(suffix="秒")
        self.cooldown.setMaximumWidth(270)
        self.cooldown.setMinimumWidth(130)
        self.cooldown.setAccessibleName("共用发送冷却（秒）")
        self.cooldown.setPlaceholderText("例如 0.8")
        self.hotkey_error = label("两个频道不能使用同一个快捷键。", "error", True)
        self.cooldown_error = label("请输入 0.2–2 秒之间的数字。", "error", True)
        for title, control, error in (("队伍聊天快捷键", self.team_key, None),
                                      ("全体聊天快捷键", self.all_key, self.hotkey_error),
                                      ("共用发送冷却", self.cooldown, self.cooldown_error)):
            caption = label(title)
            caption.setBuddy(control)
            form.addRow(caption, control)
            if error is not None:
                error.hide()
                form.addRow("", error)
        self.category_mode = CutComboBox(wheel_changes=False)
        self.category_mode.setAccessibleName("多类别发送方式")
        for mode, title in CATEGORY_MODES.items():
            self.category_mode.addItem(title, mode)
        form.addRow("多类别发送方式", self.category_mode)
        if host.wheel_settings is not None:
            self.wheel_button = action_button(self, "", self.open_wheel_settings)
            self.update_wheel_button()
            form.addRow("类别轮盘", self.wheel_button)
        controls.addLayout(form)
        controls.addWidget(label("冷却 0.2–2 秒，两个频道共用；快捷键须不同。", "muted", True))
        self.category_mode.setToolTip("逐类：发完当前类别再换下一类。交替：每发一条换下一类。空类别自动跳过。")
        controls.addWidget(separator())
        controls.addWidget(label("界面与启动", "section"))
        self.font_size = CutComboBox(wheel_changes=False)
        self.font_size.setAccessibleName("字体大小")
        for size in FONT_SIZES:
            self.font_size.addItem(f"{size} px" + ("（默认）" if size == DEFAULT_CONFIG["font_size"] else ""), size)
        font_form = QFormLayout()
        font_form.setHorizontalSpacing(14)
        font_caption = label("字体大小")
        font_caption.setBuddy(self.font_size)
        font_form.addRow(font_caption, self.font_size)
        controls.addLayout(font_form)
        self.font_size.setToolTip("保存后调整界面字号，下次启动保留。")
        self.start_hidden = TacticalCheckBox("启动后隐藏到系统托盘")
        self.autostart = TacticalCheckBox("随 Windows 登录自动启动")
        controls.addWidget(self.start_hidden)
        self.start_hidden.setToolTip("下次启动时生效。")
        controls.addWidget(self.autostart)
        controls.addWidget(label("关闭窗口后仍在托盘运行；完全退出请使用托盘菜单。", "muted", True))
        self.error_label = label("", "error", True)
        self.error_label.hide()
        controls.addStretch()
        columns.addWidget(left, 3)

        right = Panel()
        right.setMinimumWidth(270)
        about = QVBoxLayout(right)
        about.setContentsMargins(16, 14, 16, 14)
        about.setSpacing(8)
        about.addWidget(label("关于与更新", "section"))
        brand_row = QHBoxLayout()
        brand_icon = QLabel()
        brand_icon.setPixmap(self.host.windowIcon().pixmap(32, 32))
        brand_row.addWidget(brand_icon)
        brand_details = QVBoxLayout()
        brand_details.addWidget(label("ValorantToxicTamer", wrap=True))
        brand_details.addWidget(label(f"当前版本   V{VERSION}", "muted", True))
        brand_row.addLayout(brand_details, 1)
        about.addLayout(brand_row)
        about.addWidget(separator())
        self.update_channel = CutComboBox(wheel_changes=False)
        self.update_channel.setAccessibleName("更新渠道")
        for key, title in UPDATE_CHANNELS.items():
            self.update_channel.addItem(title, key)
        channel_caption = label("更新渠道 · 自动保存", "muted")
        channel_caption.setBuddy(self.update_channel)
        about.addWidget(channel_caption)
        about.addWidget(self.update_channel)
        self.update_channel_hint = label("", "muted", True)
        about.addWidget(self.update_channel_hint)
        self.repair_update_button = CutButton("恢复更新设置")
        about.addWidget(self.repair_update_button)
        self.update_button = UpdateButton()
        self.update_button.clicked.connect(lambda: self.host.updater.check())
        self.update_progress = QProgressBar()
        self.update_progress.setAccessibleName("更新下载进度")
        self.update_progress.setRange(0, 1000)
        self.update_progress.hide()
        self.cancel_update_button = CutButton("取消更新")
        self.cancel_update_button.clicked.connect(self.host.updater.cancel_update)
        self.cancel_update_button.hide()
        self.host.updater.bind_widgets(self)
        update_actions = QHBoxLayout()
        update_actions.addWidget(self.update_button, 1)
        update_actions.addWidget(self.cancel_update_button)
        self.update_download_page = CutButton("打开下载页")
        self.update_download_page.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(RELEASES_PAGE)))
        about.addLayout(update_actions)
        about.addWidget(self.update_download_page)
        about.addWidget(self.update_progress)
        about.addWidget(separator())
        about.addWidget(label("本地数据", "section"))
        path_label = label(str(self.host.messages.path.parent), "muted", True)
        path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setToolTip(str(self.host.messages.path.parent))
        about.addWidget(path_label)
        path_actions = QHBoxLayout()
        self.open_data_button = CutButton("打开文件夹")
        self.open_data_button.clicked.connect(self.open_data_folder)
        self.copy_path_button = CutButton("复制路径")
        self.copy_path_button.clicked.connect(self.copy_data_path)
        path_actions.addWidget(self.open_data_button)
        path_actions.addWidget(self.copy_path_button)
        about.addLayout(path_actions)
        about.addStretch()
        columns.addWidget(right, 2)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        outer.addWidget(self.error_label)
        footer = QHBoxLayout()
        self.settings_hint = label("修改后点击「保存设置」生效", "muted", True)
        footer.addWidget(self.settings_hint, 1)
        self.discard_button = action_button(self, "放弃修改", self.load_settings)
        self.discard_button.setToolTip("恢复已保存的常规设置；不会改变自动保存的更新渠道。")
        footer.addWidget(self.discard_button)
        self.save_button = action_button(self, "保存设置", self.apply_settings, primary=True)
        self.save_button.setMinimumWidth(180)
        footer.addWidget(self.save_button)
        outer.addLayout(footer)
        for control in (self.team_key, self.all_key, self.font_size, self.category_mode):
            control.currentIndexChanged.connect(self.settings_changed)
        self.cooldown.textChanged.connect(self.settings_changed)
        self.start_hidden.toggled.connect(self.settings_changed)
        self.autostart.toggled.connect(self.settings_changed)

    def update_wheel_button(self):
        value = self.host.wheel_settings
        state = "有错误" if value.error else "已启用" if value.enabled else "已关闭"
        self.wheel_button.setText(f"配置轮盘… · {state}")

    def open_wheel_settings(self):
        if not self.host.management.can_edit():
            return
        dialog = WheelSettingsDialog(self.host)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.update_wheel_button()
                self.host.refresh_status()
        finally:
            dialog.deleteLater()

    def load_settings(self):
        value = self.host.config.value
        self.team_key.setCurrentText(value["team_hotkey"])
        self.all_key.setCurrentText(value["all_hotkey"])
        self.cooldown.setText(str(value["cooldown"]))
        self.start_hidden.setChecked(value["start_hidden"])
        self.autostart.setChecked(value["autostart"])
        self.font_size.setCurrentIndex(self.font_size.findData(value["font_size"]))
        self.category_mode.setCurrentIndex(self.category_mode.findData(value["category_mode"]))
        self.settings_changed()

    def open_data_folder(self):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.host.messages.path.parent))):
            self.host.error("无法打开数据文件夹，请复制路径后手动打开。")

    def copy_data_path(self):
        QApplication.clipboard().setText(str(self.host.messages.path.parent))
        self.host.result_label.setText("本地数据路径已复制。")

    def settings_changed(self, *_):
        value = self.host.config.value
        try:
            cooldown = float(self.cooldown.text().strip())
        except ValueError:
            cooldown = None
        changed = (self.team_key.currentText() != value["team_hotkey"] or
                   self.all_key.currentText() != value["all_hotkey"] or
                   cooldown != value["cooldown"] or
                   self.font_size.currentData() != value["font_size"] or
                   self.category_mode.currentData() != value["category_mode"] or
                   self.start_hidden.isChecked() != value["start_hidden"] or
                   self.autostart.isChecked() != value["autostart"])
        self.has_changes = changed
        self.settings_hint.setText("有未保存的修改 · 保存后生效" if changed else "设置已保存")
        self.settings_hint.setStyleSheet("color: #e9bd75;" if changed else "")
        self.update_save_actions(self.host.management.can_edit())
        self.error_label.hide()
        if self.team_key.currentText() != self.all_key.currentText():
            self.hotkey_error.hide()
            self.all_key.setAccessibleDescription("")
        if cooldown is not None and 0.2 <= cooldown <= 2:
            self.cooldown_error.hide()
            self.cooldown.setAccessibleDescription("")

    def update_save_actions(self, idle):
        enabled = idle and self.has_changes
        self.save_button.setEnabled(enabled)
        self.discard_button.setEnabled(enabled)

    def show_field_error(self, control, error):
        self.error_label.hide()
        error.show()
        control.setAccessibleDescription(error.text())
        control.setFocus()
        QTimer.singleShot(0, self, lambda: self.form_scroll.ensureWidgetVisible(
            error, 0, control.height() + 8))

    def apply_settings(self):
        if self.team_key.currentText() == self.all_key.currentText():
            self.show_field_error(self.all_key, self.hotkey_error)
            return
        try:
            cooldown = float(self.cooldown.text().strip())
        except ValueError:
            cooldown = None
        if cooldown is None or not 0.2 <= cooldown <= 2:
            self.show_field_error(self.cooldown, self.cooldown_error)
            self.cooldown.selectAll()
            return
        try:
            value = dict(team_hotkey=self.team_key.currentText(), all_hotkey=self.all_key.currentText(),
                         cooldown=cooldown, start_hidden=self.start_hidden.isChecked(),
                         autostart=self.autostart.isChecked(), font_size=self.font_size.currentData(),
                         category_mode=self.category_mode.currentData())
            font_changed = value["font_size"] != self.host.config.value["font_size"]
            def save():
                self.host.save_settings(value)
                self.host.messages.set_mode(self.host.config.value["category_mode"])
            self.host.sender.edit(save)
            self.host.refresh_status()
            if font_changed:
                self.host.apply_font_size()
            self.host.result_label.setText("设置已保存。")
            self.settings_changed()
        except (OSError, ValueError) as exc:
            self.error_label.setText(f"未保存：{exc}")
            self.error_label.show()
            self.host.error(exc)


class WheelSettingsDialog(QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setWindowTitle("类别轮盘")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        settings = host.wheel_settings
        self.enabled = TacticalCheckBox("启用类别轮盘")
        self.enabled.setChecked(settings.enabled)
        layout.addWidget(self.enabled)
        layout.addWidget(label("游戏前台按住左 Alt 1 秒打开。移动鼠标选类，左键加入、右键移除，松开 Alt 确认。", "muted", True))
        layout.addWidget(label("游戏仍会接收鼠标操作，可能转动准星或触发开火。", "muted", True))
        layout.addWidget(label(
            f"按勾选顺序排列，最多 {WHEEL_LIMIT} 类。取消后重新勾选可移到末尾。", "muted", True))
        self.options = QListWidget()
        self.options.setAccessibleName("轮盘预设类别")
        self.options.setUniformItemSizes(True)
        self.options.setMinimumHeight(156)
        self.entries = {category["id"]: category["name"] for category in host.messages.categories}
        self.order = [cid for cid in settings.categories if cid in self.entries]
        for cid in self.entries:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, cid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if cid in self.order else Qt.CheckState.Unchecked)
            self.options.addItem(item)
        self.render_order()
        self.options.itemChanged.connect(self.selection_changed)
        layout.addWidget(self.options)
        self.error = label(settings.error or "", "error", True)
        self.error.setVisible(bool(settings.error))
        layout.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(action_button(self, "取消", self.reject))
        buttons.addWidget(action_button(self, "保存轮盘", self.save, primary=True))
        layout.addLayout(buttons)

    def render_order(self):
        indices = {cid: index for index, cid in enumerate(self.order, 1)}
        with QSignalBlocker(self.options):
            for row in range(self.options.count()):
                item = self.options.item(row)
                cid = item.data(Qt.ItemDataRole.UserRole)
                name = self.entries[cid]
                title = f"{indices[cid]}. {name}" if cid in indices else name
                if not self.host.messages.category_count(cid):
                    title += "（无消息）"
                item.setText(title)

    def selection_changed(self, item):
        cid = item.data(Qt.ItemDataRole.UserRole)
        checked = item.checkState() == Qt.CheckState.Checked
        self.error.hide()
        if checked and cid not in self.order:
            if len(self.order) >= WHEEL_LIMIT:
                with QSignalBlocker(self.options):
                    item.setCheckState(Qt.CheckState.Unchecked)
                self.error.setText(f"轮盘最多选择 {WHEEL_LIMIT} 个类别。")
                self.error.show()
                return
            self.order.append(cid)
        elif not checked and cid in self.order:
            self.order.remove(cid)
        self.render_order()

    def save(self):
        try:
            self.host.save_wheel_settings(self.enabled.isChecked(), tuple(self.order))
        except (OSError, ValueError) as exc:
            self.error.setText(str(exc))
            self.error.show()
        else:
            self.accept()

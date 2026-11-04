from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPen
from PySide6.QtWidgets import (QDialog, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QScrollArea, QSizePolicy, QStackedWidget, QStyle,
    QStyledItemDelegate, QTabWidget, QVBoxLayout, QWidget)

from .config_manager import FONT_SIZES, HOTKEYS
from .app_version import VERSION
from .tray import app_icon
from .update_controller import UpdateController
from .ui_theme import (MUTED, RED, TEXT, CutButton, CutComboBox, CutLineEdit,
                      CutTabBar, MessageDialog, Panel, TacticalCheckBox, style_for_font_size,
                      style_message_box)


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


class MessageDelegate(QStyledItemDelegate):
    def __init__(self, window):
        super().__init__(window.list_widget)
        self.window = window

    def column_widths(self):
        metrics = self.window.list_widget.fontMetrics()
        digits = max(2, len(str(self.window.list_widget.count())))
        number = max(36, max(metrics.horizontalAdvance(str(i) * digits) for i in range(10)))
        upcoming_font = QFont(self.window.list_widget.font())
        upcoming_font.setPointSizeF(max(8, upcoming_font.pointSizeF() - 1))
        upcoming = max(60, QFontMetrics(upcoming_font).horizontalAdvance("下一条"))
        return number, upcoming

    def sizeHint(self, option, index):
        number, upcoming = self.column_widths()
        reserved = number + upcoming + 40
        width = max(1, self.window.list_widget.viewport().width() - reserved)
        text = index.data(Qt.ItemDataRole.UserRole) or ""
        rect = self.window.list_widget.fontMetrics().boundingRect(
            QRect(0, 0, width, 100000), Qt.TextFlag.TextWordWrap, text)
        return QSize(width + reserved, max(62, rect.height() + 30))

    def paint(self, painter, option, index):
        painter.save()
        painter.setClipRect(option.rect)
        rect = option.rect
        number_width, upcoming_width = self.column_widths()
        upcoming = index.row() == self.window.next_index
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(rect, QColor("#2b3e50"))
        elif upcoming:
            painter.fillRect(rect, QColor("#38232e"))
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
        painter.drawText(QRect(rect.left() + number_width + 24, rect.top() + 14,
                               rect.width() - number_width - upcoming_width - 40, rect.height() - 28),
                         Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignVCenter,
                         index.data(Qt.ItemDataRole.UserRole) or "")
        if upcoming:
            font = QFont(option.font)
            font.setPointSizeF(max(8, font.pointSizeF() - 1))
            painter.setFont(font)
            painter.setPen(QColor("#ff8290"))
            painter.drawText(QRect(rect.right() - upcoming_width - 6, rect.top(), upcoming_width, rect.height()),
                             Qt.AlignmentFlag.AlignCenter, "下一条")
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(QPen(QColor("#6c8296"), 1, Qt.PenStyle.DashLine))
            painter.drawRect(rect.adjusted(5, 4, -5, -4))
        painter.restore()


class MessageList(QListWidget):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.doItemsLayout()


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


class MainWindow(QMainWindow):
    def __init__(self, messages, config, sender, save_settings):
        super().__init__()
        self.messages, self.config, self.sender = messages, config, sender
        self.save_settings = save_settings
        self.setWindowTitle(f"ValorantToxicTamer · V{VERSION}")
        self.setWindowIcon(app_icon())
        self.resize(1120, 850)
        self.setMinimumSize(860, 680)
        self.setStyleSheet(style_for_font_size(config.value["font_size"]))
        self.next_index = -1
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
        self.edit_buttons = []
        self.tabs.addTab(self.build_management(), "消息管理")
        self.tabs.addTab(self.build_settings(), "设置")
        layout.addWidget(separator())
        self.result_label = label("就绪 · 请添加消息，然后在游戏前台使用快捷键。", wrap=True)
        layout.addWidget(self.result_label)
        layout.addWidget(label("发送前请关闭游戏聊天框，并松开修饰键。程序无法确认聊天框状态或服务器送达。",
                               "muted", True))
        self.load_settings()
        self.reload_messages()
        self.apply_font_size()
        if self.messages.messages:
            self.result_label.setText("就绪 · 在游戏前台使用快捷键，按顺序输入下一条消息。")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(100)

    def button(self, text, action, *, primary=False, icon=None):
        button = CutButton(text, primary=primary)
        if icon is not None:
            button.setIcon(self.style().standardIcon(icon))
        button.clicked.connect(action)
        return button

    def build_management(self):
        management = QWidget()
        columns = QHBoxLayout(management)
        columns.setContentsMargins(0, 16, 0, 0)
        columns.setSpacing(16)
        preview = Panel()
        preview.setMinimumWidth(220)
        preview.setMaximumWidth(330)
        card = QVBoxLayout(preview)
        card.setContentsMargins(22, 24, 22, 22)
        card.setSpacing(18)
        card.addWidget(label("下一条", "section"))
        self.progress_label = WrappingLabel()
        self.progress_label.setObjectName("progress")
        card.addWidget(self.progress_label)
        card.addWidget(separator())
        self.next_label = WrappingLabel("暂无消息", minimum_lines=3)
        self.next_label.setObjectName("preview")
        self.next_label.setTextFormat(Qt.TextFormat.PlainText)
        card.addWidget(self.next_label)
        card.addStretch()
        self.state_label = label("等待添加消息", "ready", True)
        card.addWidget(self.state_label)
        keys = QFormLayout()
        self.team_hint = label("F8", "keycap")
        self.all_hint = label("F9", "keycap")
        keys.addRow("队伍", self.team_hint)
        keys.addRow("全体", self.all_hint)
        card.addLayout(keys)
        self.keys_label = label("快捷键注册中…", "muted", True)
        card.addWidget(self.keys_label)
        card.addWidget(label("单一列表 · 顺序循环", "muted"))
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.preview_scroll.setMinimumWidth(240)
        self.preview_scroll.setMaximumWidth(350)
        self.preview_scroll.setWidget(preview)
        columns.addWidget(self.preview_scroll, 3)

        workspace = Panel()
        manage_layout = QVBoxLayout(workspace)
        manage_layout.setContentsMargins(16, 20, 16, 16)
        manage_layout.setSpacing(14)
        toolbar = QHBoxLayout()
        toolbar.addWidget(label("消息列表", "section"))
        self.count_label = label("0 条", "muted")
        toolbar.addWidget(self.count_label)
        toolbar.addStretch()
        self.add_button = self.button("添加消息", self.add_message, primary=True)
        self.import_button = self.button("导入 TXT", self.import_txt)
        toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.import_button)
        manage_layout.addLayout(toolbar)
        manage_layout.addWidget(separator())
        self.message_stack = QStackedWidget()
        self.list_widget = MessageList()
        self.list_widget.setMouseTracking(True)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list_widget.setItemDelegate(MessageDelegate(self))
        self.list_widget.itemDoubleClicked.connect(self.edit_message)
        self.list_widget.currentRowChanged.connect(self.update_actions)
        self.message_stack.addWidget(self.list_widget)
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch()
        empty_title = label("还没有消息", "section")
        empty_layout.addWidget(empty_title, alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addWidget(label("添加一条消息，或导入 TXT 文件开始使用。", "muted", True),
                               alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch()
        self.message_stack.addWidget(empty)
        manage_layout.addWidget(self.message_stack, 1)
        manage_layout.addWidget(separator())
        buttons = QHBoxLayout()
        self.edit_button = self.button("编辑", self.edit_message)
        self.delete_button = self.button("删除", self.delete_message)
        self.clear_button = self.button("清空列表", self.clear_messages)
        self.up_button = self.button("", lambda: self.move(-1), icon=QStyle.StandardPixmap.SP_ArrowUp)
        self.down_button = self.button("", lambda: self.move(1), icon=QStyle.StandardPixmap.SP_ArrowDown)
        for button, name in ((self.up_button, "上移"), (self.down_button, "下移")):
            button.setFixedWidth(42)
            button.setAccessibleName(name)
            button.setToolTip(name)
        self.export_button = self.button("导出 TXT", self.export_txt)
        self.edit_buttons = [self.add_button, self.import_button, self.edit_button,
                             self.delete_button, self.clear_button, self.up_button, self.down_button, self.export_button]
        for button in (self.edit_button, self.delete_button, self.clear_button, self.up_button, self.down_button):
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(self.export_button)
        manage_layout.addLayout(buttons)
        manage_layout.addWidget(label("已自动保存 · 修改后从第一条开始循环；TXT 导入会追加非空行。", "muted", True))
        columns.addWidget(workspace, 7)
        return management

    def build_settings(self):
        settings = QWidget()
        outer = QVBoxLayout(settings)
        outer.setContentsMargins(0, 16, 0, 0)
        outer.setSpacing(16)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        columns = QHBoxLayout(body)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(16)
        left = Panel()
        controls = QVBoxLayout(left)
        controls.setContentsMargins(24, 24, 24, 22)
        controls.setSpacing(14)
        controls.addWidget(label("聊天快捷键", "section"))
        form = QFormLayout()
        form.setHorizontalSpacing(22)
        form.setVerticalSpacing(16)
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
        for title, control in (("队伍聊天快捷键", self.team_key),
                               ("全体聊天快捷键", self.all_key), ("共用发送冷却", self.cooldown)):
            caption = label(title)
            caption.setBuddy(control)
            form.addRow(caption, control)
        controls.addLayout(form)
        controls.addWidget(label("范围 0.2–2 秒，队伍与全体共用。", "muted", True))
        controls.addWidget(label("两个频道需使用不同快捷键。", "muted", True))
        controls.addWidget(separator())
        controls.addWidget(label("界面显示", "section"))
        self.font_size = CutComboBox(wheel_changes=False)
        self.font_size.setAccessibleName("字体大小")
        for size in FONT_SIZES:
            self.font_size.addItem(f"{size} pt" + ("（默认）" if size == 11 else ""), size)
        font_form = QFormLayout()
        font_form.setHorizontalSpacing(22)
        font_caption = label("字体大小")
        font_caption.setBuddy(self.font_size)
        font_form.addRow(font_caption, self.font_size)
        controls.addLayout(font_form)
        controls.addWidget(label("保存后调整界面字号，下次启动保留。", "muted", True))
        controls.addWidget(separator())
        controls.addWidget(label("启动与后台", "section"))
        self.start_hidden = TacticalCheckBox("启动后隐藏到系统托盘")
        self.autostart = TacticalCheckBox("随 Windows 登录自动启动")
        controls.addWidget(self.start_hidden)
        controls.addWidget(label("下次启动时生效", "muted"))
        controls.addWidget(self.autostart)
        controls.addWidget(label("关闭窗口后继续在托盘运行，完全退出请使用托盘菜单。", "muted", True))
        controls.addStretch()
        columns.addWidget(left, 3)

        right = Panel()
        right.setMinimumWidth(260)
        about = QVBoxLayout(right)
        about.setContentsMargins(24, 24, 24, 22)
        about.setSpacing(20)
        about.addWidget(label("版本与更新", "section"))
        brand_icon = QLabel()
        brand_icon.setPixmap(self.windowIcon().pixmap(58, 58))
        about.addWidget(brand_icon)
        about.addWidget(label("ValorantToxicTamer", wrap=True))
        about.addWidget(label(f"当前版本   V{VERSION}"))
        self.update_button = self.button("检查更新", lambda: self.updater.check(),
                                         icon=QStyle.StandardPixmap.SP_BrowserReload)
        self.update_button.setMaximumWidth(200)
        self.updater = UpdateController(self)
        about.addWidget(self.update_button)
        about.addWidget(separator())
        about.addWidget(label("本地数据", "section"))
        path_label = label(str(self.messages.path.parent), "muted", True)
        path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setToolTip(str(self.messages.path.parent))
        about.addWidget(path_label)
        about.addStretch()
        columns.addWidget(right, 2)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        footer = QHBoxLayout()
        self.settings_hint = label("修改后点击「保存设置」生效", "muted", True)
        footer.addWidget(self.settings_hint, 1)
        self.save_button = self.button("保存设置", self.apply_settings, primary=True)
        self.save_button.setMinimumWidth(180)
        footer.addWidget(self.save_button)
        outer.addLayout(footer)
        for control in (self.team_key, self.all_key, self.font_size):
            control.currentIndexChanged.connect(self.settings_changed)
        self.cooldown.textChanged.connect(self.settings_changed)
        self.start_hidden.toggled.connect(self.settings_changed)
        self.autostart.toggled.connect(self.settings_changed)
        return settings

    def load_settings(self):
        value = self.config.value
        self.team_key.setCurrentText(value["team_hotkey"])
        self.all_key.setCurrentText(value["all_hotkey"])
        self.cooldown.setText(str(value["cooldown"]))
        self.start_hidden.setChecked(value["start_hidden"])
        self.autostart.setChecked(value["autostart"])
        self.font_size.setCurrentIndex(self.font_size.findData(value["font_size"]))
        self.settings_changed()

    def apply_font_size(self):
        self.setStyleSheet(style_for_font_size(self.config.value["font_size"]))
        self.next_label.update_height()
        self.progress_label.update_height()
        self.list_widget.doItemsLayout()

    def settings_changed(self, *_):
        value = self.config.value
        try:
            cooldown = float(self.cooldown.text().strip())
        except ValueError:
            cooldown = None
        changed = (self.team_key.currentText() != value["team_hotkey"] or
                   self.all_key.currentText() != value["all_hotkey"] or
                   cooldown != value["cooldown"] or
                   self.font_size.currentData() != value["font_size"] or
                   self.start_hidden.isChecked() != value["start_hidden"] or
                   self.autostart.isChecked() != value["autostart"])
        self.settings_hint.setText("有未保存的修改 · 点击「保存设置」生效" if changed
                                   else "设置已保存 · 修改后点击「保存设置」生效")

    def apply_settings(self):
        try:
            try:
                cooldown = float(self.cooldown.text().strip())
            except ValueError:
                raise ValueError("请输入有效的冷却时间（0.2–2 秒）。") from None
            value = dict(team_hotkey=self.team_key.currentText(), all_hotkey=self.all_key.currentText(),
                         cooldown=cooldown, start_hidden=self.start_hidden.isChecked(),
                         autostart=self.autostart.isChecked(), font_size=self.font_size.currentData())
            self.sender.edit(lambda: self.save_settings(value))
            self.refresh_status()
            self.apply_font_size()
            self.result_label.setText("设置已保存。")
            self.settings_changed()
        except (OSError, ValueError) as exc:
            self.error(exc)
            self.load_settings()

    def set_hotkey_status(self, status):
        self.keys_label.setText(f"队伍：{status['team']}\n全体：{status['all']}")
        self.team_hint.setText(self.config.value["team_hotkey"])
        self.all_hint.setText(self.config.value["all_hotkey"])

    def update_actions(self, *_):
        if not hasattr(self, "save_button"):
            return
        row = self.list_widget.currentRow()
        count = self.list_widget.count()
        with self.sender.lock:
            idle = not self.sender.busy
        self.add_button.setEnabled(idle)
        self.import_button.setEnabled(idle)
        self.edit_button.setEnabled(idle and row >= 0)
        self.delete_button.setEnabled(idle and row >= 0)
        self.clear_button.setEnabled(idle and count > 0)
        self.up_button.setEnabled(idle and row > 0)
        self.down_button.setEnabled(idle and 0 <= row < count - 1)
        self.export_button.setEnabled(idle and count > 0)
        self.save_button.setEnabled(idle)

    def refresh_status(self):
        with self.sender.lock:
            count, index = len(self.messages.messages), self.messages.index
            remaining = max(0, self.sender.ready_at - self.sender.clock())
            state = ("正在输入" if self.sender.busy else f"冷却 {remaining:.1f}s" if remaining
                     else "就绪" if count else "等待添加消息")
            current = self.messages.current or "暂无消息"
        position = index + 1 if count else 0
        self.state_label.setText(f"● {state}  |  {position} / {count}")
        self.progress_label.setText(f'<span style="color:{RED}">{position:02d}</span>'
                                    f' <span style="font-size:{self.config.value["font_size"] + 9}pt">/ {count:02d}</span>')
        if self.next_label.text() != current:
            self.next_label.setText(current)
            self.next_label.setToolTip(current)
            self.preview_scroll.verticalScrollBar().setValue(0)
        next_index = index if count else -1
        if self.next_index != next_index:
            self.next_index = next_index
            self.list_widget.viewport().update()
        self.update_actions()

    def report(self, message):
        self.result_label.setText(message)
        self.refresh_status()

    def reload_messages(self, row=0):
        self.list_widget.clear()
        for i, text in enumerate(self.messages.messages):
            item = QListWidgetItem(f"{i + 1:02d}   {text}")
            item.setData(Qt.ItemDataRole.UserRole, text)
            item.setToolTip(text)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, f"第 {i + 1} 条：{text}")
            self.list_widget.addItem(item)
        self.list_widget.setCurrentRow(min(row, len(self.messages.messages) - 1))
        self.message_stack.setCurrentIndex(0 if self.messages.messages else 1)
        self.count_label.setText(f"{len(self.messages.messages)} 条")
        self.refresh_status()
        self.list_widget.viewport().update()

    def change(self, action, row=0):
        try:
            self.sender.edit(action)
            self.reload_messages(row)
            self.result_label.setText("消息已保存，循环从第一条开始。")
        except (OSError, ValueError) as exc:
            self.error(exc)

    def add_message(self):
        dialog = MessageDialog(self, "添加消息")
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        text = dialog.input.text().strip()
        dialog.deleteLater()
        if accepted:
            self.change(lambda: self.messages.replace(self.messages.messages + [text]), len(self.messages.messages))

    def edit_message(self, *_):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        dialog = MessageDialog(self, "编辑消息", self.messages.messages[row], row)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        text = dialog.input.text().strip()
        dialog.deleteLater()
        if accepted:
            values = self.messages.messages.copy()
            values[row] = text
            self.change(lambda: self.messages.replace(values), row)

    def delete_message(self):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("删除消息")
        dialog.setText("确定删除选中的消息？")
        dialog.setInformativeText(f"第 {row + 1:02d} 条：{self.messages.messages[row]}\n删除后循环从第一条开始。")
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText("删除")
        dialog.button(QMessageBox.StandardButton.No).setText("取消")
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        style_message_box(dialog, QMessageBox.StandardButton.Yes)
        answer = dialog.exec()
        dialog.deleteLater()
        if answer == QMessageBox.StandardButton.Yes:
            values = self.messages.messages.copy()
            values.pop(row)
            self.change(lambda: self.messages.replace(values), row)

    def clear_messages(self):
        count = len(self.messages.messages)
        if not count:
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("清空消息列表")
        dialog.setText(f"确定删除列表中的全部 {count} 条消息？")
        dialog.setInformativeText("清空后会自动保存，无法撤销。如需保留，请先取消并导出 TXT 备份。")
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText("清空列表")
        dialog.button(QMessageBox.StandardButton.No).setText("取消")
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.setEscapeButton(QMessageBox.StandardButton.No)
        style_message_box(dialog, QMessageBox.StandardButton.Yes)
        answer = dialog.exec()
        dialog.deleteLater()
        if answer == QMessageBox.StandardButton.Yes:
            self.change(lambda: self.messages.replace([]))

    def move(self, direction):
        row = self.list_widget.currentRow()
        target = row + direction
        if row >= 0 and 0 <= target < len(self.messages.messages):
            values = self.messages.messages.copy()
            values[row], values[target] = values[target], values[row]
            self.change(lambda: self.messages.replace(values), target)

    def import_txt(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入 TXT（追加到列表）", "", "文本文件 (*.txt)")
        if path:
            self.change(lambda: self.messages.import_txt(Path(path)))

    def export_txt(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出 TXT", "messages.txt", "文本文件 (*.txt)")
        if path:
            try:
                self.messages.export_txt(Path(path))
                self.result_label.setText(f"已导出到 {path}")
            except (OSError, ValueError) as exc:
                self.error(exc)

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

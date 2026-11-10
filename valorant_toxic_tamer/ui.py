from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, QTimer, QThread, Slot
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPen
from PySide6.QtWidgets import (QDialog, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QScrollArea, QSizePolicy, QStackedWidget, QStyle,
    QStyledItemDelegate, QTabWidget, QVBoxLayout, QWidget)

from .config_manager import DEFAULT_CONFIG, FONT_SIZES, HOTKEYS
from .message_manager import deduplicate_messages, prepare_txt_import
from .app_version import VERSION
from .tray import app_icon
from .update_controller import UpdateController
from .update_settings import UPDATE_CHANNELS
from .ui_theme import (MUTED, RED, TEXT, CutButton, CutComboBox, CutLineEdit,
                      CutTabBar, MessageDialog, Panel, TacticalCheckBox, style_for_font_size,
                      style_message_box, UpdateButton)


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
        self._column_key = None
        self._column_widths = None

    def column_widths(self):
        digits = max(2, len(str(self.window.list_widget.count())))
        key = (self.window.list_widget.font().toString(), digits)
        if key == self._column_key:
            return self._column_widths
        metrics = self.window.list_widget.fontMetrics()
        number = max(36, max(metrics.horizontalAdvance(str(i) * digits) for i in range(10)))
        upcoming_font = QFont(self.window.list_widget.font())
        upcoming_font.setPixelSize(max(8, upcoming_font.pixelSize() - 1))
        upcoming = max(60, QFontMetrics(upcoming_font).horizontalAdvance("下一条"))
        self._column_key = key
        self._column_widths = number, upcoming
        return self._column_widths

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
            font.setPixelSize(max(8, font.pixelSize() - 1))
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


class ImportWorker(QThread):
    def __init__(self, path, existing, parent):
        super().__init__(parent)
        self.path, self.existing = path, existing
        self.preview = None
        self.error = None

    def run(self):
        try:
            self.preview = prepare_txt_import(self.path, self.existing)
        except Exception as exc:
            self.error = str(exc)


class ImportDialog(QDialog):
    def __init__(self, parent, preview):
        super().__init__(parent)
        self.preview = preview
        self.setWindowTitle("导入预览")
        self.setWindowIcon(parent.windowIcon())
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        layout.addWidget(label("导入预览", "section"))
        layout.addWidget(label(
            f"读取到 {len(preview.messages)} 条非空消息，其中 {preview.duplicate_count} 条与现有消息或文件内前面的消息重复。",
            wrap=True))
        self.skip_duplicates = TacticalCheckBox("跳过重复消息（按完整内容比较）")
        self.skip_duplicates.setAccessibleName("跳过重复消息")
        layout.addWidget(self.skip_duplicates)
        layout.addWidget(label("前 5 条内容预览", "muted"))
        self.preview_text = WrappingLabel()
        self.preview_text.setTextFormat(Qt.TextFormat.PlainText)
        self.preview_text.setText("\n".join(
            f"{i + 1}. {text[:100]}{'…' if len(text) > 100 else ''}"
            for i, text in enumerate(preview.messages[:5])))
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.preview_scroll.setMinimumHeight(120)
        self.preview_scroll.setMaximumHeight(220)
        self.preview_scroll.setWidget(self.preview_text)
        layout.addWidget(self.preview_scroll)
        self.summary = label("", wrap=True)
        layout.addWidget(self.summary)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = CutButton("取消")
        cancel.clicked.connect(self.reject)
        cancel.setDefault(True)
        self.confirm = CutButton("追加导入", primary=True)
        self.confirm.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(self.confirm)
        layout.addLayout(actions)
        self.skip_duplicates.toggled.connect(self.update_summary)
        self.update_summary()

    def selected_messages(self):
        return self.preview.unique_messages if self.skip_duplicates.isChecked() else self.preview.messages

    def update_summary(self):
        count = len(self.selected_messages())
        self.summary.setText(f"将追加 {count} 条消息；确认后自动保存，发送循环从第一条开始。")
        self.confirm.setEnabled(count > 0)


class MainWindow(QMainWindow):
    def __init__(self, messages, config, sender, save_settings):
        super().__init__()
        self.messages, self.config, self.sender = messages, config, sender
        self.save_settings = save_settings
        self.settings_loaded = False
        self.import_worker = None
        self.closing = False
        self.updater = UpdateController(self)
        self.setWindowTitle(f"ValorantToxicTamer · V{VERSION}")
        self.setWindowIcon(app_icon())
        self.resize(1067, 669)
        self._initial_size_applied = False
        self.setMinimumSize(840, 638)
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
        self.reload_messages()
        self.apply_font_size()
        if self.messages.messages:
            self.result_label.setText("就绪 · 在游戏前台使用快捷键，按顺序输入下一条消息。")
        if self.updater.preferences_error:
            self.result_label.setText("更新设置无法读取，暂用正式版渠道；可在设置页恢复。消息管理和快捷发送仍可使用。")

    def _page_changed(self, page):
        if page == 1:
            self.ensure_settings()

    def ensure_settings(self):
        if self.settings_loaded:
            return
        settings = self.build_settings()
        current = self.tabs.currentIndex()
        self.tabs.blockSignals(True)
        self.tabs.removeTab(1)
        self.tabs.insertTab(1, settings, "设置")
        self.tabs.setCurrentIndex(current)
        self.tabs.blockSignals(False)
        self.settings_placeholder.deleteLater()
        self.settings_loaded = True
        self.load_settings()
        self.update_actions()

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
        self.search = CutLineEdit()
        self.search.setAccessibleName("搜索消息")
        self.search.setPlaceholderText("搜索消息内容（不改变发送顺序）")
        self.search.setClearButtonEnabled(True)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(150)
        self.search_timer.timeout.connect(self.filter_messages)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        manage_layout.addWidget(self.search)
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
        self.no_matches = label("没有匹配的消息，试试其他关键词。", "muted", True)
        self.no_matches.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_stack.addWidget(self.no_matches)
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
            self.font_size.addItem(f"{size} px" + ("（默认）" if size == DEFAULT_CONFIG["font_size"] else ""), size)
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
        about.setSpacing(14)
        about.addWidget(label("版本与更新", "section"))
        brand_row = QHBoxLayout()
        brand_icon = QLabel()
        brand_icon.setPixmap(self.windowIcon().pixmap(44, 44))
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
        self.update_button.clicked.connect(lambda: self.updater.check())
        self.update_progress = QProgressBar()
        self.update_progress.setAccessibleName("更新下载进度")
        self.update_progress.setRange(0, 1000)
        self.update_progress.hide()
        self.cancel_update_button = CutButton("取消更新")
        self.cancel_update_button.clicked.connect(self.updater.cancel_update)
        self.cancel_update_button.hide()
        self.updater.bind_widgets()
        update_actions = QHBoxLayout()
        update_actions.addWidget(self.update_button, 1)
        update_actions.addWidget(self.cancel_update_button)
        about.addLayout(update_actions)
        about.addWidget(self.update_progress)
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
            font_changed = value["font_size"] != self.config.value["font_size"]
            self.sender.edit(lambda: self.save_settings(value))
            self.refresh_status()
            if font_changed:
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
        row = self.list_widget.currentRow()
        count = self.list_widget.count()
        with self.sender.lock:
            idle = not self.sender.busy and self.import_worker is None
        selected = row >= 0 and not self.list_widget.item(row).isHidden()
        self.add_button.setEnabled(idle)
        self.import_button.setEnabled(idle)
        self.edit_button.setEnabled(idle and selected)
        self.delete_button.setEnabled(idle and selected)
        self.clear_button.setEnabled(idle and count > 0)
        # Reordering a filtered subset would obscure the actual adjacent message.
        filtered = bool(self.search.text().strip())
        self.up_button.setEnabled(idle and selected and row > 0 and not filtered)
        self.down_button.setEnabled(idle and selected and row < count - 1 and not filtered)
        self.export_button.setEnabled(idle and count > 0)
        if self.settings_loaded:
            self.save_button.setEnabled(idle)

    def refresh_status(self):
        with self.sender.lock:
            count, index = len(self.messages.messages), self.messages.index
            remaining = max(0, self.sender.ready_at - self.sender.clock())
            busy = self.sender.busy
            state = ("正在输入" if busy else f"冷却 {remaining:.1f}s" if remaining
                     else "就绪" if count else "等待添加消息")
            current = self.messages.current or "暂无消息"
        position = index + 1 if count else 0
        self.state_label.setText(f"● {state}  |  {position} / {count}")
        self.progress_label.setText(f'<span style="color:{RED}">{position:02d}</span>'
                                    f' <span style="font-size:{self.config.value["font_size"] + 9}px">/ {count:02d}</span>')
        if self.next_label.text() != current:
            self.next_label.setText(current)
            self.next_label.setToolTip(current)
            self.preview_scroll.verticalScrollBar().setValue(0)
        next_index = index if count else -1
        if self.next_index != next_index:
            self.next_index = next_index
            self.list_widget.viewport().update()
        self.update_actions()

        if self.isVisible() and (busy or remaining > 0):
            if not self.timer.isActive():
                self.timer.start()
        else:
            self.timer.stop()

    def report(self, message):
        self.result_label.setText(message)
        if self.isVisible():
            self.refresh_status()

    def reload_messages(self, row=0):
        self.list_widget.setUpdatesEnabled(False)
        blocked = self.list_widget.blockSignals(True)
        try:
            self.list_widget.clear()
            for i, text in enumerate(self.messages.messages):
                item = QListWidgetItem(f"{i + 1:02d}   {text}")
                item.setData(Qt.ItemDataRole.UserRole, text)
                item.setToolTip(text)
                item.setData(Qt.ItemDataRole.AccessibleTextRole, f"第 {i + 1} 条：{text}")
                self.list_widget.addItem(item)
            self.list_widget.setCurrentRow(min(row, len(self.messages.messages) - 1))
            self.filter_messages()
        finally:
            self.list_widget.blockSignals(blocked)
            self.list_widget.setUpdatesEnabled(True)
        self.refresh_status()
        self.list_widget.viewport().update()

    def filter_messages(self):
        self.search_timer.stop()
        query = self.search.text().strip().casefold()
        visible = []
        self.list_widget.setUpdatesEnabled(False)
        try:
            for row, text in enumerate(self.messages.messages):
                matches = not query or query in text.casefold()
                self.list_widget.item(row).setHidden(not matches)
                if matches:
                    visible.append(row)
            current = self.list_widget.currentRow()
            if current not in visible:
                self.list_widget.setCurrentRow(visible[0] if visible else -1)
        finally:
            self.list_widget.setUpdatesEnabled(True)
        count = len(self.messages.messages)
        self.count_label.setText(f"{len(visible)} / {count} 条" if query else f"{count} 条")
        self.message_stack.setCurrentIndex(1 if not count else 0 if visible else 2)
        self.update_actions()

    def change(self, action, row=0):
        if self.import_worker is not None or self.closing:
            return
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
        if self.import_worker is not None or self.closing:
            return
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
        if self.import_worker is not None or self.closing:
            return
        path, _ = QFileDialog.getOpenFileName(self, "导入 TXT（追加到列表）", "", "文本文件 (*.txt)")
        if path:
            self.import_worker = ImportWorker(Path(path), tuple(self.messages.messages), self)
            self.import_worker.finished.connect(self._import_prepared)
            self.result_label.setText("正在读取并检查导入文件…")
            self.update_actions()
            self.import_worker.start()

    @Slot()
    def _import_prepared(self):
        worker = self.import_worker
        if worker is None:
            return
        try:
            if self.closing:
                return
            if worker.error:
                self.error(worker.error)
                self.result_label.setText("导入未完成，现有消息未更改。")
                return
            # Keep the import guard until the modal preview has closed too.
            dialog = ImportDialog(self, worker.preview)
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            skip_duplicates = dialog.skip_duplicates.isChecked()
            dialog.deleteLater()
        finally:
            self.import_worker = None
            worker.deleteLater()
            self.update_actions()
        if accepted and not self.closing:
            try:
                def append():
                    # Recompute inside the same edit lock as persistence, using
                    # all input lines rather than the preview's old unique subset.
                    incoming = (deduplicate_messages(worker.preview.messages, self.messages.messages)
                                if skip_duplicates else worker.preview.messages)
                    if not incoming:
                        return False
                    self.messages.replace(self.messages.messages + list(incoming))
                    return True
                row = len(self.messages.messages)
                if self.sender.edit(append):
                    self.reload_messages(row)
                    self.result_label.setText("消息已保存，循环从第一条开始。")
                else:
                    self.result_label.setText("没有需要追加的新消息，现有消息和发送进度未更改。")
            except (OSError, ValueError) as exc:
                self.error(exc)
        else:
            self.result_label.setText("已取消导入，现有消息未更改。")

    def shutdown(self):
        self.closing = True
        self.timer.stop()
        self.search_timer.stop()
        if self.import_worker:
            self.import_worker.wait()
        self.updater.shutdown()

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

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_size_applied:
            # The default size includes the native title bar and window borders.
            frame_size = self.frameGeometry().size() - self.size()
            self.resize(QSize(1067, 669) - frame_size)
            self._initial_size_applied = True
        self.refresh_status()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

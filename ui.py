from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog,
    QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from config_manager import HOTKEYS
from app_version import VERSION
from tray import app_icon
from update_controller import UpdateController


STYLE = """
QWidget { background: #101823; color: #e5edf6; font: 10pt 'Microsoft YaHei UI'; }
QMainWindow { background: #101823; }
QLabel#brand { font-size: 23pt; font-weight: 700; }
QLabel#muted { color: #91a4b8; }
QFrame#card { background: #192535; border: 1px solid #29394b; border-radius: 8px; }
QFrame#card QLabel { background: transparent; }
QPushButton { background: #26394d; border: 1px solid #3b526c; border-radius: 5px; padding: 7px 14px; }
QPushButton:hover { background: #354e68; }
QPushButton:disabled { color: #667789; background: #1a2634; }
QPushButton#primary { background: #cd3d51; border: 1px solid #fa566b; color: white; }
QListWidget { background: #131e2b; border: 1px solid #314357; border-radius: 5px; padding: 5px; }
QListWidget::item { padding: 10px; border-bottom: 1px solid #263548; }
QListWidget::item:selected { background: #31475f; color: white; }
QTabWidget::pane { border: 0; }
QTabBar::tab { padding: 11px 24px; background: #192535; }
QTabBar::tab:selected { border-bottom: 3px solid #ff5364; }
QComboBox, QLineEdit { background: #223247; padding: 6px; border: 1px solid #425971; }
QMenu { background: #192535; }
QMenu::item { padding: 7px 22px; }
QMenu::item:selected { background: #31475f; }
"""


class MainWindow(QMainWindow):
    def __init__(self, messages, config, sender, save_settings):
        super().__init__()
        self.messages, self.config, self.sender = messages, config, sender
        self.save_settings = save_settings
        self.setWindowTitle(f"ValorantToxicTamer · V{VERSION}")
        self.setWindowIcon(app_icon())
        self.resize(880, 740)
        self.setMinimumSize(700, 620)
        self.setStyleSheet(STYLE)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(26, 22, 26, 18)
        layout.setSpacing(15)
        brand = QLabel("ValorantToxicTamer")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        subtitle = QLabel("快捷沟通 · 单一列表 · 顺序循环")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 14, 18, 14)
        self.state_label = QLabel()
        self.keys_label = QLabel("快捷键注册中…")
        self.keys_label.setWordWrap(True)
        self.next_label = QLabel()
        self.next_label.setWordWrap(True)
        self.next_label.setTextFormat(Qt.TextFormat.PlainText)
        self.next_label.setMaximumHeight(100)
        for item in (self.state_label, self.keys_label, self.next_label):
            card_layout.addWidget(item)
        layout.addWidget(card)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        management = QWidget()
        manage_layout = QVBoxLayout(management)
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self.edit_message)
        manage_layout.addWidget(self.list_widget, 1)
        buttons = QHBoxLayout()
        self.edit_buttons = []
        for label, action in (("添加", self.add_message), ("编辑", self.edit_message),
                              ("删除", self.delete_message), ("上移", lambda: self.move(-1)),
                              ("下移", lambda: self.move(1)), ("TXT 导入", self.import_txt),
                              ("TXT 导出", self.export_txt)):
            button = QPushButton(label)
            button.clicked.connect(action)
            if label == "添加":
                button.setObjectName("primary")
            buttons.addWidget(button)
            self.edit_buttons.append(button)
        manage_layout.addLayout(buttons)
        note = QLabel("修改列表后从第一条开始；TXT 导入会追加非空行。所有更改自动保存。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        manage_layout.addWidget(note)
        self.tabs.addTab(management, "消息管理")

        settings = QWidget()
        form = QFormLayout(settings)
        form.setVerticalSpacing(18)
        self.team_key, self.all_key = QComboBox(), QComboBox()
        for box in (self.team_key, self.all_key):
            box.addItems(HOTKEYS)
        self.cooldown = QLineEdit()
        self.cooldown.setPlaceholderText("例如 0.8")
        cooldown_row = QHBoxLayout()
        cooldown_row.addWidget(self.cooldown, 1)
        cooldown_row.addWidget(QLabel("秒（0.2–2）"))
        self.start_hidden = QCheckBox("启动后隐藏到系统托盘")
        self.autostart = QCheckBox("随 Windows 登录自动启动")
        form.addRow("队伍聊天快捷键", self.team_key)
        form.addRow("全体聊天快捷键", self.all_key)
        form.addRow("共用发送冷却", cooldown_row)
        form.addRow("后台运行", self.start_hidden)
        form.addRow("程序启动", self.autostart)
        fixed = QLabel("关闭主窗口始终隐藏到托盘；完全退出请使用托盘菜单。")
        fixed.setWordWrap(True)
        form.addRow(fixed)
        self.save_button = QPushButton("保存设置")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.apply_settings)
        form.addRow(self.save_button)
        self.update_button = QPushButton("检查更新")
        self.updater = UpdateController(self)
        self.update_button.clicked.connect(self.updater.check)
        form.addRow(f"当前版本：V{VERSION}", self.update_button)
        path_label = QLabel(f"本地数据：{messages.path.parent}")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setWordWrap(True)
        form.addRow(path_label)
        self.tabs.addTab(settings, "设置")

        warning = QLabel("触发前请关闭游戏聊天框并松开修饰键。程序无法确认聊天框状态或服务器送达。")
        warning.setObjectName("muted")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.result_label = QLabel("就绪 · 请添加消息，然后在游戏前台使用快捷键。")
        self.result_label.setTextFormat(Qt.TextFormat.PlainText)
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        self.load_settings()
        self.reload_messages()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(100)

    def load_settings(self):
        value = self.config.value
        self.team_key.setCurrentText(value["team_hotkey"])
        self.all_key.setCurrentText(value["all_hotkey"])
        self.cooldown.setText(str(value["cooldown"]))
        self.start_hidden.setChecked(value["start_hidden"])
        self.autostart.setChecked(value["autostart"])

    def apply_settings(self):
        try:
            try:
                cooldown = float(self.cooldown.text().strip())
            except ValueError:
                raise ValueError("请输入有效的冷却时间（0.2–2 秒）。") from None
            value = dict(team_hotkey=self.team_key.currentText(), all_hotkey=self.all_key.currentText(),
                         cooldown=cooldown, start_hidden=self.start_hidden.isChecked(),
                         autostart=self.autostart.isChecked())
            self.sender.edit(lambda: self.save_settings(value))
            self.result_label.setText("设置已保存。")
        except (OSError, ValueError) as exc:
            self.error(exc)
            self.load_settings()

    def set_hotkey_status(self, status):
        self.keys_label.setText(f"队伍  {status['team']}    /    全体  {status['all']}")

    def refresh_status(self):
        with self.sender.lock:
            count, index = len(self.messages.messages), self.messages.index
            remaining = max(0, self.sender.ready_at - self.sender.clock())
            state = "正在输入" if self.sender.busy else f"冷却 {remaining:.1f}s" if remaining else "已启用"
            self.state_label.setText(f"● {state}    |    当前序号 {index + 1 if count else 0} / {count}")
            current = self.messages.current or "暂无消息"
            self.next_label.setText("下一条：" + (current[:240] + "…" if len(current) > 240 else current))
            for button in self.edit_buttons + [self.save_button]:
                button.setEnabled(not self.sender.busy)

    def report(self, message):
        self.result_label.setText(message)
        self.refresh_status()

    def reload_messages(self, row=0):
        self.list_widget.clear()
        self.list_widget.addItems([f"{i + 1:02d}   {text}" for i, text in enumerate(self.messages.messages)])
        self.list_widget.setCurrentRow(min(row, len(self.messages.messages) - 1))
        self.refresh_status()

    def change(self, action, row=0):
        try:
            self.sender.edit(action)
            self.reload_messages(row)
            self.result_label.setText("消息已保存，循环从第一条开始。")
        except (OSError, ValueError) as exc:
            self.error(exc)

    def add_message(self):
        text, ok = QInputDialog.getText(self, "添加消息", "消息内容（单行）：")
        if ok:
            self.change(lambda: self.messages.replace(self.messages.messages + [text.strip()]),
                        len(self.messages.messages))

    def edit_message(self, *_):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        text, ok = QInputDialog.getText(self, "编辑消息", "消息内容（单行）：",
                                       text=self.messages.messages[row])
        if ok:
            values = self.messages.messages.copy()
            values[row] = text.strip()
            self.change(lambda: self.messages.replace(values), row)

    def delete_message(self):
        row = self.list_widget.currentRow()
        if row >= 0 and QMessageBox.question(self, "删除消息", "删除选中的消息？") == QMessageBox.StandardButton.Yes:
            values = self.messages.messages.copy()
            values.pop(row)
            self.change(lambda: self.messages.replace(values), row)

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
        QMessageBox.warning(self, "操作未完成", str(error))

    def reveal(self, page=0):
        self.tabs.setCurrentIndex(page)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        self.hide()
        event.ignore()

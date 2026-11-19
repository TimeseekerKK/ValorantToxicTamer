"""TXT import worker and preview dialog, independent of main-window layout."""
import threading

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QDialog, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from .import_process import prepare_import as prepare_txt_import
from .ui_theme import CutButton, CutComboBox, TacticalCheckBox
from .ui_widgets import WrappingLabel, label, separator


class ImportWorker(QThread):
    def __init__(self, path, existing, parent):
        super().__init__(parent)
        self.path, self.existing = path, existing
        self.preview = None
        self.error = None
        self.cancel = threading.Event()

    def run(self):
        try:
            self.preview = prepare_txt_import(self.path, self.existing, self.cancel)
        except Exception as exc:
            self.error = str(exc)


class ImportDialog(QDialog):
    def __init__(self, parent, preview, categories, destination):
        super().__init__(parent)
        self.preview = preview
        self.setWindowTitle("导入预览")
        self.setWindowIcon(parent.windowIcon())
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        layout.addWidget(label("导入预览", "section"))
        destination_row = QHBoxLayout()
        destination_label = label("目标类别")
        self.destination = CutComboBox(wheel_changes=False)
        self.destination.setAccessibleName("导入目标类别")
        for category in categories:
            self.destination.addItem(category["name"], category["id"])
        self.destination.setCurrentIndex(self.destination.findData(destination))
        destination_label.setBuddy(self.destination)
        destination_row.addWidget(destination_label)
        destination_row.addWidget(self.destination, 1)
        destination_row.addStretch()
        layout.addLayout(destination_row)
        layout.addWidget(label(
            f"读取到 {len(preview.messages)} 条非空消息，其中 {preview.duplicate_count} 条与现有消息或文件内前面的消息重复。",
            wrap=True))
        self.skip_duplicates = TacticalCheckBox("跳过重复消息（按完整内容比较）")
        self.skip_duplicates.setAccessibleName("跳过重复消息")
        layout.addWidget(self.skip_duplicates)
        shown = preview.messages[:5]
        layout.addWidget(label(f"预览前 {len(shown)} 条" if len(shown) < len(preview.messages) else "内容预览", "muted"))
        content = QWidget()
        rows = QVBoxLayout(content)
        rows.setContentsMargins(0, 0, 4, 0)
        self.preview_status = []
        unique_index = 0
        for i, text in enumerate(shown, 1):
            # Unique messages keep the order of their first eligible occurrence.
            duplicate = (unique_index == len(preview.unique_messages)
                         or text != preview.unique_messages[unique_index])
            if not duplicate:
                unique_index += 1
            row = QHBoxLayout()
            message = WrappingLabel()
            message.setTextFormat(Qt.TextFormat.PlainText)
            message.setText(f"{i}. {text[:100]}{'…' if len(text) > 100 else ''}")
            status = label("")
            status.setStyleSheet("color: #e9bd75;" if duplicate else "color: #68ded2;")
            self.preview_status.append((status, duplicate))
            row.addWidget(message, 1)
            row.addWidget(status, 0, Qt.AlignmentFlag.AlignTop)
            rows.addLayout(row)
            rows.addWidget(separator())
        rows.addStretch()
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.preview_scroll.setMinimumHeight(80)
        self.preview_scroll.setMaximumHeight(max(80, 36 * len(shown) + 4))
        self.preview_scroll.setWidget(content)
        layout.addWidget(self.preview_scroll)
        self.summary = label("", "progress", True)
        layout.addWidget(self.summary)
        layout.addWidget(label("确认后自动保存，目标类别和全部消息的发送进度将重置。", "muted", True))
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = CutButton("取消")
        cancel.clicked.connect(self.reject)
        cancel.setDefault(True)
        self.confirm = CutButton("", primary=True)
        self.confirm.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(self.confirm)
        layout.addLayout(actions)
        self.skip_duplicates.toggled.connect(self.update_summary)
        self.update_summary()

    def selected_messages(self):
        return self.preview.unique_messages if self.skip_duplicates.isChecked() else self.preview.messages

    def update_summary(self):
        skip = self.skip_duplicates.isChecked()
        for status, duplicate in self.preview_status:
            status.setText(("重复 · 已跳过" if skip else "重复 · 将保留") if duplicate else "将追加")
        count = len(self.selected_messages())
        skipped = f"，跳过 {self.preview.duplicate_count} 条重复消息" if skip and self.preview.duplicate_count else ""
        self.summary.setText(f"将追加 {count} 条消息{skipped}。")
        self.confirm.setText(f"追加 {count} 条")
        self.confirm.setEnabled(count > 0)

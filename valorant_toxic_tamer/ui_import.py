"""TXT import worker and preview dialog, independent of main-window layout."""
import threading

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QDialog, QHBoxLayout, QScrollArea, QVBoxLayout

from .import_process import prepare_import as prepare_txt_import
from .ui_theme import CutButton, TacticalCheckBox
from .ui_widgets import WrappingLabel, label


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
        self.destination_label = label("", wrap=True)
        self.destination_label.hide()
        layout.addWidget(self.destination_label)
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
        self.summary.setText(f"将追加 {count} 条消息；确认后自动保存，目标类别和全部消息从第一条开始。")
        self.confirm.setEnabled(count > 0)

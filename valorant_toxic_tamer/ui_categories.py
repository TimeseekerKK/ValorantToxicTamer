"""Category-management dialog and its guarded persistence actions."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QMessageBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .message_manager import ALL_CATEGORY, UNCATEGORIZED
from .ui_theme import CutButton, MessageDialog, style_message_box
from .ui_widgets import label, separator


class CategoryManagerDialog(QDialog):
    """Category operations are kept away from message editing controls."""
    def __init__(self, page):
        window = page.host
        super().__init__(window)
        self.page = page
        self.host = window
        self.setWindowTitle("管理类别")
        self.setWindowIcon(window.windowIcon())
        self.setStyleSheet(window.styleSheet())
        self.setMinimumSize(620, 480)
        self.resize(720, 580)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        layout.addWidget(label("管理类别", "section"))
        layout.addWidget(label("在这里整理类别。添加、编辑消息请回到消息管理。", "muted", True))
        self.table = QTableWidget(0, 3)
        self.table.setAccessibleName("类别名称、消息数量和类别操作")
        self.table.setHorizontalHeaderLabels(["类别名称", "消息数量", "操作"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setStyleSheet("""
            QTableWidget { background: #16232f; border: 1px solid #435364; }
            QTableWidget::item { padding: 8px; border-bottom: 1px solid #30404f; }
            QHeaderView::section { background: #2b3e50; color: #edf2f6; border: 0; padding: 10px; }
        """)
        layout.addWidget(self.table, 1)
        layout.addWidget(separator())
        self.create_button = CutButton("新建类别…", primary=True)
        self.create_button.clicked.connect(self.create_category)
        self.create_button.setDefault(True)
        self.status_label = label("删除类别后，其中的消息将移到“未分类”，不会删除消息。", "muted", True)
        layout.addWidget(self.status_label)
        footer = QHBoxLayout()
        footer.addWidget(self.create_button)
        footer.addStretch()
        self.done_button = CutButton("完成")
        self.done_button.clicked.connect(self.accept)
        footer.addWidget(self.done_button)
        layout.addLayout(footer)
        self.reload_categories()

    def reload_categories(self):
        manager = self.host.messages
        categories = [{"id": ALL_CATEGORY, "name": "全部消息"}] + manager.categories
        self.action_buttons = []
        self.table.setRowCount(0)
        self.table.setRowCount(len(categories))
        action_width = 0
        for row, category in enumerate(categories):
            cid = category["id"]
            name = QTableWidgetItem(category["name"])
            name.setData(Qt.ItemDataRole.UserRole, cid)
            name.setToolTip(category["name"])
            self.table.setItem(row, 0, name)
            count = QTableWidgetItem(str(manager.category_count(cid)))
            count.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 1, count)
            if cid in (ALL_CATEGORY, UNCATEGORIZED):
                self.table.setItem(row, 2, QTableWidgetItem("内置汇总" if cid == ALL_CATEGORY else "内置类别"))
                self.table.setRowHeight(row, 52)
                continue
            actions = QWidget()
            buttons = QHBoxLayout(actions)
            buttons.setContentsMargins(4, 4, 4, 4)
            buttons.setSpacing(6)
            rename = CutButton("重命名")
            rename.setAccessibleName(f"重命名类别：{category['name']}")
            rename.clicked.connect(lambda _=False, cid=cid: self.rename_category(cid))
            delete = CutButton("删除类别")
            delete.setAccessibleName(f"删除类别：{category['name']}")
            delete.clicked.connect(lambda _=False, cid=cid: self.delete_category(cid))
            for button in (rename, delete):
                buttons.addWidget(button)
                self.action_buttons.append(button)
            self.table.setCellWidget(row, 2, actions)
            # Item padding also reduces the geometry given to cell widgets.
            self.table.setRowHeight(row, max(68, rename.sizeHint().height() + 26,
                                             delete.sizeHint().height() + 26))
            action_width = max(action_width, actions.sizeHint().width())
        self.table.setColumnWidth(2, max(220, action_width))
        self.update_actions()

    def update_actions(self):
        with self.host.sender.lock:
            idle = (not self.host.sender.busy and self.page.import_worker is None
                    and not self.host.closing)
        for control in [self.create_button, *self.action_buttons]:
            control.setEnabled(idle)

    def apply_change(self, action):
        try:
            if self.page.import_worker is not None or self.host.closing:
                raise ValueError("当前正在导入或退出，请稍后再修改类别。")
            if self.host.sender.edit(action) is False:
                self.status_label.setText("类别未变化，未重复保存，发送进度保持不变。")
                return False
        except (OSError, ValueError) as exc:
            dialog = QMessageBox(QMessageBox.Icon.Warning, "类别未保存", str(exc),
                                 QMessageBox.StandardButton.Ok, self)
            style_message_box(dialog, QMessageBox.StandardButton.Ok)
            dialog.exec()
            dialog.deleteLater()
            return False
        self.page.reload_messages(self.page.list_widget.currentRow())
        self.reload_categories()
        self.status_label.setText("类别已自动保存。删除类别时，消息会保留到“未分类”。")
        return True

    def create_category(self):
        dialog = MessageDialog(self, "新建类别", field_label="类别名称",
                               hint="名称不能为空或重复，最多 40 个字符。",
                               confirm_text="新建类别")
        dialog.input.setMaxLength(40)
        dialog.input.setPlaceholderText("输入类别名称")
        while dialog.exec() == QDialog.DialogCode.Accepted:
            name = dialog.input.text().strip()
            if self.apply_change(lambda: self.host.messages.create_category(name)):
                break
        dialog.deleteLater()

    def rename_category(self, cid):
        dialog = MessageDialog(self, "重命名类别", self.host.messages.category_name(cid),
                               field_label="类别名称", hint="名称不能重复，最多 40 个字符；发送进度保留。",
                               confirm_text="保存名称")
        dialog.input.setMaxLength(40)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        name = dialog.input.text().strip()
        dialog.deleteLater()
        if accepted:
            self.apply_change(lambda: self.host.messages.rename_category(cid, name))

    def delete_category(self, cid):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("删除类别")
        dialog.setText(f"确定删除类别“{self.host.messages.category_name(cid)}”？")
        dialog.setInformativeText("其中的消息会移到“未分类”，不会删除消息。该类别将退出发送范围。")
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText("删除类别")
        dialog.button(QMessageBox.StandardButton.No).setText("取消")
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        style_message_box(dialog, QMessageBox.StandardButton.Yes)
        answer = dialog.exec()
        dialog.deleteLater()
        if answer == QMessageBox.StandardButton.Yes:
            self.apply_change(lambda: self.host.messages.delete_category(cid))

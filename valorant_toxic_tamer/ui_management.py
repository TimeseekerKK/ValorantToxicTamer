"""Message-management page: editing, filtering, category selection and file I/O.

The page owns its controls, incremental list state and import worker. Shared
services and window-level notifications are accessed explicitly through host.
"""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Slot, QItemSelectionModel
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QScrollArea, QSizePolicy,
    QStackedWidget, QStyle, QVBoxLayout, QWidget)

from .message_manager import ALL_CATEGORY, UNCATEGORIZED, CATEGORY_MODES, deduplicate_messages
from .ui_categories import CategoryManagerDialog
from .ui_import import ImportDialog, ImportWorker
from .ui_theme import CutButton, CutComboBox, CutLineEdit, MessageDialog, Panel, style_message_box
from .ui_widgets import (CategoryOrderDelegate, ElidingLabel, MessageDelegate, MessageList,
                         WrappingLabel, action_button, label, separator)


class ManagementPage(QWidget):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.import_worker = None
        self.category_dialog = None
        self.next_index = -1
        self._render_revision = -1
        self._category_signature = None
        self._items_by_key = {}
        self._suspended_state = None
        columns = QHBoxLayout(self)
        columns.setContentsMargins(0, 8, 0, 0)
        columns.setSpacing(12)
        preview = Panel()
        card = QVBoxLayout(preview)
        card.setContentsMargins(14, 12, 14, 12)
        card.setSpacing(6)
        card.addWidget(label("下一条发送", "section"))
        progress = QHBoxLayout()
        self.active_category_label = ElidingLabel("ready")
        self.progress_label = WrappingLabel()
        self.progress_label.setObjectName("progress")
        self.progress_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        progress.addWidget(self.active_category_label, 1)
        progress.addWidget(self.progress_label)
        card.addLayout(progress)
        card.addWidget(separator())
        self.next_label = WrappingLabel("暂无消息")
        self.next_label.setObjectName("preview")
        self.next_label.setTextFormat(Qt.TextFormat.PlainText)
        self.next_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setAccessibleName("下一条消息正文")
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.preview_scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        self.preview_scroll.setMinimumHeight(40)
        self.preview_scroll.setWidget(self.next_label)
        card.addWidget(self.preview_scroll, 1)
        card.addWidget(separator())
        self.state_label = label("等待添加消息", "ready")
        card.addWidget(self.state_label)
        keys = QHBoxLayout()
        self.team_hint = label("F8", "keycap")
        self.all_hint = label("F9", "keycap")
        keys.addWidget(label("队伍"))
        keys.addWidget(self.team_hint)
        keys.addWidget(label("全体"))
        keys.addWidget(self.all_hint)
        card.addLayout(keys)
        self.keys_label = label("快捷键注册中…", "muted")
        card.addWidget(self.keys_label)
        self.pause_button = self.button("暂停发送", self.toggle_pause)
        self.pause_button.setToolTip("暂停两个频道的快捷发送，保留发送范围与进度；本次运行有效。")
        card.addWidget(self.pause_button)
        category_panel = Panel()
        category_layout = QVBoxLayout(category_panel)
        category_layout.setContentsMargins(14, 12, 14, 12)
        category_layout.setSpacing(6)
        scope_header = QHBoxLayout()
        self.send_scope_title = label("发送范围", "section")
        scope_header.addWidget(self.send_scope_title)
        scope_header.addStretch()
        self.send_scope_label = label("", "muted")
        scope_header.addWidget(self.send_scope_label)
        category_layout.addLayout(scope_header)
        self.send_categories = QListWidget()
        self.send_categories.setItemDelegate(CategoryOrderDelegate(self.send_categories))
        self.send_categories.setAccessibleName("发送范围：勾选参与发送的类别")
        self.send_categories.setToolTip("勾选框内数字表示发送顺序，取消后自动补位；全部消息与其他类别互斥。取消所有勾选可暂停发送。")
        self.send_categories.setUniformItemSizes(True)
        self.send_categories.setStyleSheet("""
            QListWidget::item { min-height: 26px; padding: 1px 3px; }
            QListWidget::indicator { width: 26px; height: 24px; border: 1px solid #8595a5; }
            QListWidget::indicator:unchecked { background: #121d27; }
            QListWidget::indicator:checked { background: #38645f; }
        """)
        self.send_categories.itemChanged.connect(self.send_category_changed)
        category_layout.addWidget(self.send_categories)
        mode_row = QHBoxLayout()
        self.send_mode_caption = label("发送方式")
        mode_row.addWidget(self.send_mode_caption)
        self.send_mode = ElidingLabel("muted")
        mode_row.addWidget(self.send_mode, 1)
        category_layout.addLayout(mode_row)
        self.restore_cycle_button = self.button("恢复循环", self.restore_cycle)
        self.restore_cycle_button.hide()
        category_layout.addWidget(self.restore_cycle_button, alignment=Qt.AlignmentFlag.AlignRight)
        sidebar = QWidget()
        sidebar.setMinimumWidth(240)
        sidebar.setMaximumWidth(300)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(10)
        sidebar_layout.addWidget(category_panel)
        sidebar_layout.addWidget(preview, 1)
        columns.addWidget(sidebar, 3)

        workspace = Panel()
        manage_layout = QVBoxLayout(workspace)
        manage_layout.setContentsMargins(12, 10, 12, 10)
        manage_layout.setSpacing(6)
        toolbar = QHBoxLayout()
        toolbar.addWidget(label("消息列表", "section"))
        self.count_label = label("0 条", "muted")
        toolbar.addWidget(self.count_label)
        toolbar.addStretch()
        self.add_button = self.button("添加消息", self.add_message, primary=True)
        self.import_button = self.button("导入", self.import_txt)
        toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.import_button)
        self.cancel_import_button = self.button("取消导入", self.cancel_import)
        self.cancel_import_button.hide()
        toolbar.addWidget(self.cancel_import_button)
        manage_layout.addLayout(toolbar)
        category_bar = QHBoxLayout()
        category_bar.setSpacing(8)
        category_bar.addWidget(label("列表筛选"))
        self.view_category = CutComboBox(wheel_changes=False)
        self.view_category.setAccessibleName("按类别筛选消息，不改变发送范围")
        self.view_category.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.view_category.setMinimumWidth(136)
        self.view_category.setMaximumWidth(190)
        self.view_category.currentIndexChanged.connect(self.filter_messages)
        category_bar.addWidget(self.view_category, 1)
        self.manage_categories_button = self.button("管理类别", self.manage_categories)
        self.search = CutLineEdit()
        self.search.setAccessibleName("搜索消息")
        self.search.setPlaceholderText("搜索消息…")
        self.search.setToolTip("仅筛选列表，不改变发送范围或顺序。")
        self.search.setMinimumWidth(90)
        self.search.setClearButtonEnabled(True)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(150)
        self.search_timer.timeout.connect(self.filter_messages)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        category_bar.addWidget(self.search, 2)
        category_bar.addWidget(self.manage_categories_button)
        manage_layout.addLayout(category_bar)
        manage_layout.addWidget(label("筛选和搜索仅影响列表", "muted"))
        manage_layout.addWidget(separator())
        self.message_stack = QStackedWidget()
        self.list_widget = MessageList()
        self.list_widget.setMouseTracking(True)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list_widget.setItemDelegate(MessageDelegate(self))
        self.list_widget.itemDoubleClicked.connect(self.edit_message)
        self.list_widget.currentRowChanged.connect(self.update_actions)
        self.list_widget.itemSelectionChanged.connect(self.update_actions)
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
        no_results = QWidget()
        no_results_layout = QVBoxLayout(no_results)
        no_results_layout.addStretch()
        self.no_matches = label("", "progress", True)
        self.no_matches.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_results_layout.addWidget(self.no_matches)
        search_actions = QHBoxLayout()
        search_actions.addStretch()
        self.clear_search_button = self.button("清除关键词", self.clear_search)
        self.search_all_button = self.button("搜索全部类别", self.search_all, primary=True)
        search_actions.addWidget(self.clear_search_button)
        search_actions.addWidget(self.search_all_button)
        search_actions.addStretch()
        no_results_layout.addLayout(search_actions)
        no_results_layout.addStretch()
        self.message_stack.addWidget(no_results)
        manage_layout.addWidget(self.message_stack, 1)
        manage_layout.addWidget(separator())
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.selection_label = label("已选 0 条", "muted")
        buttons.addWidget(self.selection_label)
        self.edit_button = self.button("编辑", self.edit_message)
        self.delete_button = self.button("删除", self.delete_message)
        self.up_button = self.button("", lambda: self.move(-1), icon=QStyle.StandardPixmap.SP_ArrowUp)
        self.down_button = self.button("", lambda: self.move(1), icon=QStyle.StandardPixmap.SP_ArrowDown)
        for button, name in ((self.up_button, "上移"), (self.down_button, "下移")):
            button.setFixedWidth(36)
            button.setAccessibleName(name)
            button.setToolTip(name)
        self.more_button = self.button("更多 ⋯", lambda: None)
        self.more_menu = QMenu(self.more_button)
        self.export_action = self.more_menu.addAction("导出 TXT")
        self.export_action.triggered.connect(self.export_txt)
        self.more_menu.addSeparator()
        self.backup_action = self.more_menu.addAction("备份消息库…")
        self.backup_action.triggered.connect(self.export_backup)
        self.restore_action = self.more_menu.addAction("恢复消息库…")
        self.restore_action.triggered.connect(self.restore_backup)
        self.more_menu.addSeparator()
        self.clear_action = self.more_menu.addAction("清空全部消息…")
        self.clear_action.triggered.connect(self.clear_messages)
        self.more_button.setMenu(self.more_menu)
        self.assign_category_button = CutButton("移动到类别…")
        self.move_category_menu = QMenu(self.assign_category_button)
        self.move_category_menu.triggered.connect(lambda action: self.assign_category(action.data()))
        self.assign_category_button.setMenu(self.move_category_menu)
        self.edit_buttons = [self.add_button, self.import_button, self.edit_button,
                             self.delete_button, self.up_button, self.down_button,
                             self.assign_category_button, self.more_button]
        for button in (self.edit_button, self.delete_button, self.up_button, self.down_button):
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(self.assign_category_button)
        buttons.addWidget(self.more_button)
        manage_layout.addLayout(buttons)
        footer = QHBoxLayout()
        footer.addWidget(label("已自动保存", "muted"))
        footer.addStretch()
        self.reorder_hint = label("清除搜索后可调整顺序", "muted")
        footer.addWidget(self.reorder_hint)
        manage_layout.addLayout(footer)
        columns.addWidget(workspace, 7)

    def button(self, text, action, *, primary=False, icon=None):
        return action_button(self, text, action, primary=primary, icon=icon)

    def toggle_pause(self):
        try:
            self.host.sender.set_paused(not self.host.sender.paused)
        except ValueError as exc:
            self.host.error(exc)
            return
        self.host.report("快捷发送已暂停，发送范围与进度保持不变。" if self.host.sender.paused
                         else "快捷发送已继续 · 游戏前台使用快捷键")

    def begin_shutdown(self):
        self.search_timer.stop()
        self.list_widget.layout_timer.stop()
        self.cancel_import()

    def shutdown(self):
        self.begin_shutdown()
        if self.import_worker:
            self.import_worker.wait()

    def sync_categories(self):
        categories = [{"id": ALL_CATEGORY, "name": "全部消息"}] + self.host.messages.categories
        selected = self.host.messages.selected_categories
        signature = tuple((c["id"], c["name"]) for c in categories)
        structure_changed = signature != self._category_signature
        if structure_changed:
            current = self.view_category.currentData()
            blocked = self.view_category.blockSignals(True)
            try:
                self.view_category.clear()
                for category in categories:
                    self.view_category.addItem(category["name"], category["id"])
                self.view_category.setCurrentIndex(max(0, self.view_category.findData(current)))
            finally:
                self.view_category.blockSignals(blocked)
            self.move_category_menu.clear()
            for category in categories[1:]:
                action = self.move_category_menu.addAction(category["name"].replace("&", "&&"))
                action.setData(category["id"])
        blocked = self.send_categories.blockSignals(True)
        try:
            if structure_changed:
                existing = {self.send_categories.item(row).data(Qt.ItemDataRole.UserRole):
                            self.send_categories.item(row) for row in range(self.send_categories.count())}
                wanted = {category["id"] for category in categories}
                for row in reversed(range(self.send_categories.count())):
                    if self.send_categories.item(row).data(Qt.ItemDataRole.UserRole) not in wanted:
                        self.send_categories.takeItem(row)
                for row, category in enumerate(categories):
                    item = existing.get(category["id"])
                    if item is None:
                        item = QListWidgetItem()
                        item.setData(Qt.ItemDataRole.UserRole, category["id"])
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        self.send_categories.insertItem(row, item)
                    elif (current_row := self.send_categories.row(item)) != row:
                        self.send_categories.insertItem(row, self.send_categories.takeItem(current_row))
            orders = {cid: order for order, cid in enumerate(selected, 1)}
            for row, category in enumerate(categories):
                cid = category["id"]
                order = orders.get(cid)
                item = self.send_categories.item(row)
                item.setText(f"{category['name']} ({self.host.messages.category_count(cid)})")
                item.setData(CategoryOrderDelegate.ORDER_ROLE, order)
                item.setData(Qt.ItemDataRole.AccessibleDescriptionRole,
                             f"发送顺序 {order}" if order is not None else "未参与发送")
                item.setToolTip(category["name"])
                item.setCheckState(Qt.CheckState.Checked if cid in selected else Qt.CheckState.Unchecked)
        finally:
            self.send_categories.blockSignals(blocked)
        self.resize_category_list()
        self.update_send_order()
        self._category_signature = signature

    def resize_category_list(self):
        row_height = self.send_categories.sizeHintForRow(0)
        self.send_categories.setFixedHeight(min(4, self.send_categories.count()) * row_height)

    def resize_progress(self):
        label = self.progress_label
        label.setFixedWidth(min(156, label.fontMetrics().horizontalAdvance(label.text()) + 2))
        label.update_height()

    def update_send_order(self):
        selected = self.host.messages.selected_categories
        names = [self.host.messages.category_name(cid) for cid in selected]
        order = " → ".join(names) if names else "未勾选类别，快捷发送已暂停"
        summary = "已选全部" if selected == [ALL_CATEGORY] else f"已选 {len(selected)} 类"
        self.send_scope_label.setText(summary)
        self.send_scope_label.setToolTip(order)
        self.send_scope_label.setAccessibleDescription(order)
        wheel = self.host.messages.wheel_categories
        if wheel:
            names_by_id = {category["id"]: category["name"] for category in self.host.messages.categories}
            labels = " → ".join(names_by_id.get(cid, "已删除类别") for cid in wheel)
            mode = "锁定" if len(wheel) == 1 else "交替"
            self.send_mode.set_full_text(f"{mode} · {labels}")
        else:
            self.send_mode.set_full_text(CATEGORY_MODES[self.host.messages.mode])
        self.send_scope_title.setText("原发送范围" if wheel else "发送范围")
        self.send_mode_caption.setVisible(not wheel)
        self.restore_cycle_button.setVisible(bool(wheel))

    def restore_cycle(self):
        if not self.can_edit():
            return
        try:
            self.host.sender.select_wheel_categories(())
        except ValueError as exc:
            self.host.error(exc)
        else:
            self.host.report("已恢复原发送范围和循环方式。")

    def send_category_changed(self, item):
        rendered = self._render_revision == self.host.messages.revision
        cid = item.data(Qt.ItemDataRole.UserRole)
        selected = self.host.messages.selected_categories
        checked = item.checkState() == Qt.CheckState.Checked
        if checked and cid not in selected:
            selected = ([ALL_CATEGORY] if cid == ALL_CATEGORY
                        else [c for c in selected if c != ALL_CATEGORY] + [cid])
        elif not checked and cid in selected:
            selected.remove(cid)
        try:
            if self.import_worker is not None or self.host.closing:
                raise ValueError("导入期间请稍后再修改发送类别")
            self.host.sender.edit(lambda: self.host.messages.select_categories(selected))
        except (OSError, ValueError) as exc:
            self.host.error(exc)
        if rendered:
            self._render_revision = self.host.messages.revision
        self.sync_categories()
        self.host.refresh_status()

    def manage_categories(self):
        with self.host.sender.lock:
            if self.host.sender.busy or self.import_worker is not None or self.host.closing:
                return
        if self.category_dialog is not None:
            return
        self.category_dialog = CategoryManagerDialog(self)
        try:
            self.category_dialog.exec()
        finally:
            self.category_dialog.deleteLater()
            self.category_dialog = None
            self.host.refresh_status()

    def selected_rows(self):
        return sorted(self.list_widget.row(item) for item in self.list_widget.selectedItems()
                      if not item.isHidden())

    def assign_category(self, cid):
        rows = self.selected_rows()
        if rows:
            self.change(lambda: self.host.messages.move_to_category(rows, cid), rows[0])

    def can_edit(self):
        with self.host.sender.lock:
            return not self.host.sender.busy and self.import_worker is None and not self.host.closing

    def update_actions(self, *_):
        row = self.list_widget.currentRow()
        idle = self.can_edit()
        rows = self.selected_rows()
        selected = row >= 0 and row in rows and len(rows) == 1
        cid = self.view_category.currentData() or ALL_CATEGORY
        category_count = self.host.messages.category_count(cid)
        self.add_button.setEnabled(idle)
        self.import_button.setEnabled(idle)
        self.edit_button.setEnabled(idle and selected)
        self.delete_button.setEnabled(idle and bool(rows))
        self.clear_action.setEnabled(idle and bool(category_count))
        # Reordering a filtered subset would obscure the actual adjacent message.
        filtered = bool(self.search.text().strip())
        offset = self.host.messages.category_offset(cid, row)
        self.up_button.setEnabled(idle and selected and offset > 0 and not filtered)
        self.down_button.setEnabled(idle and selected and 0 <= offset < category_count - 1 and not filtered)
        self.reorder_hint.setVisible(filtered)
        self.export_action.setEnabled(idle and bool(category_count))
        self.more_button.setEnabled(idle)
        self.pause_button.setEnabled(idle)
        self.restore_cycle_button.setEnabled(idle)
        importing = self.import_worker is not None and self.import_worker.isRunning()
        self.cancel_import_button.setVisible(importing)
        self.cancel_import_button.setEnabled(importing and not self.import_worker.cancel.is_set())
        self.assign_category_button.setEnabled(idle and bool(rows))
        self.selection_label.setText(f"已选 {len(rows)} 条")
        self.view_category.setEnabled(idle)
        self.search_all_button.setEnabled(idle)
        self.send_categories.setEnabled(idle)
        self.manage_categories_button.setEnabled(idle)
        self.clear_action.setText("清空全部消息…" if cid == ALL_CATEGORY
                                 else f"清空“{self.host.messages.category_name(cid)}”…")
        self.clear_action.setToolTip("不受搜索关键词影响，确认后删除当前类别的全部消息。")
        self.export_action.setText("导出全部消息 TXT" if cid == ALL_CATEGORY else "导出当前类别 TXT")
        if self.category_dialog is not None:
            self.category_dialog.update_actions()
        if self.host.settings_loaded:
            self.host.settings.update_save_actions(idle)

    def _set_message_item(self, item, row):
        text = self.host.messages.text_at(row)
        item.setText(f"{row + 1:02d}   {text}")
        item.setData(Qt.ItemDataRole.UserRole, text)
        item.setData(Qt.ItemDataRole.UserRole + 1, self.host.messages.key_at(row))
        item.setToolTip(text)
        item.setData(Qt.ItemDataRole.AccessibleTextRole, f"第 {row + 1} 条：{text}")
        self._set_message_category(item, row)

    def _set_message_category(self, item, row):
        messages = self.host.messages
        name = messages.category_name(messages.category_for(row))
        item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, name)

    def _message_view_state(self):
        selected_keys = {item.data(Qt.ItemDataRole.UserRole + 1) for item in self.list_widget.selectedItems()}
        current = self.list_widget.currentItem()
        current_key = current.data(Qt.ItemDataRole.UserRole + 1) if current else None
        anchor = self.list_widget.itemAt(self.list_widget.viewport().rect().topLeft())
        anchor_key = anchor.data(Qt.ItemDataRole.UserRole + 1) if anchor else None
        anchor_offset = self.list_widget.visualItemRect(anchor).top() if anchor else 0
        scroll = self.list_widget.verticalScrollBar().value()
        return selected_keys, current_key, anchor_key, anchor_offset, scroll

    def suspend_messages(self):
        if self._suspended_state is not None:
            return
        self.search_timer.stop()
        self.list_widget.layout_timer.stop()
        self._suspended_state = self._message_view_state()
        blocked = self.list_widget.blockSignals(True)
        try:
            self._items_by_key.clear()
            self.list_widget.clear()
            self.list_widget.itemDelegate()._sizes.clear()
        finally:
            self.list_widget.blockSignals(blocked)

    def resume_messages(self):
        if self._suspended_state is not None:
            state = self._suspended_state
            self._suspended_state = None
            self.reload_messages(view_state=state)

    def reload_messages(self, row=None, *, view_state=None):
        if self._suspended_state is not None:
            return  # The message library remains authoritative while hidden.
        self.sync_categories()
        restoring = view_state is not None
        selected_keys, current_key, anchor_key, anchor_offset, scroll = (
            view_state if restoring else self._message_view_state())
        self.list_widget.setUpdatesEnabled(False)
        blocked = self.list_widget.blockSignals(True)
        try:
            incremental = not restoring and self._render_revision + 1 == self.host.messages.revision
            kind, changed = self.host.messages.last_change if incremental else ("reset", ())
            if kind == "edit":
                for index in changed:
                    self._set_message_item(self.list_widget.item(index), index)
            elif kind == "append":
                for index in range(changed[0], self.host.messages.count):
                    item = QListWidgetItem()
                    self._set_message_item(item, index)
                    self.list_widget.addItem(item)
                    self._items_by_key[self.host.messages.key_at(index)] = item
            elif kind == "delete":
                for index in reversed(changed):
                    item = self.list_widget.takeItem(index)
                    self._items_by_key.pop(item.data(Qt.ItemDataRole.UserRole + 1), None)
                for index in range(min(changed, default=self.host.messages.count), self.host.messages.count):
                    self._set_message_item(self.list_widget.item(index), index)
            elif kind == "swap":
                first, second = sorted(changed)
                right = self.list_widget.takeItem(second)
                left = self.list_widget.takeItem(first)
                self.list_widget.insertItem(first, right)
                self.list_widget.insertItem(second, left)
                self._set_message_item(right, first)
                self._set_message_item(left, second)
            elif kind == "metadata":
                for index in range(self.host.messages.count):
                    self._set_message_category(self.list_widget.item(index), index)
            else:
                self.list_widget.clear()
                self._items_by_key.clear()
                for index in range(self.host.messages.count):
                    item = QListWidgetItem()
                    self._set_message_item(item, index)
                    self.list_widget.addItem(item)
                    self._items_by_key[self.host.messages.key_at(index)] = item
            self._render_revision = self.host.messages.revision
            target = self._items_by_key.get(current_key)
            surviving = [self._items_by_key[key] for key in selected_keys if key in self._items_by_key]
            if target is None and surviving:
                target = min(surviving, key=self.list_widget.row)
            if target is not None:
                self.list_widget.setCurrentItem(target, QItemSelectionModel.SelectionFlag.NoUpdate)
            elif self.host.messages.count:
                self.list_widget.setCurrentRow(min(row or 0, self.host.messages.count - 1))
            if row is not None and len(selected_keys) <= 1:
                self.list_widget.setCurrentRow(min(row, self.host.messages.count - 1))
            else:
                if surviving:
                    self.list_widget.clearSelection()
                    for item in surviving:
                        item.setSelected(True)
            if kind == "edit" and not self.search.text().strip():
                self.update_actions()
            else:
                self.filter_messages()
            if restoring:
                # Filtering may choose a fallback row; restore even an empty
                # selection rather than selecting an unintended first item.
                self.list_widget.clearSelection()
                for item in surviving:
                    item.setSelected(True)
                if current_key is None:
                    self.list_widget.setCurrentRow(-1)
            self.list_widget.doItemsLayout()
            anchor = self._items_by_key.get(anchor_key)
            if anchor is not None and not anchor.isHidden():
                self.list_widget.scrollToItem(anchor, QListWidget.ScrollHint.PositionAtTop)
                self.list_widget.verticalScrollBar().setValue(
                    self.list_widget.verticalScrollBar().value() - anchor_offset)
            else:
                self.list_widget.verticalScrollBar().setValue(scroll)
        finally:
            self.list_widget.blockSignals(blocked)
            self.list_widget.setUpdatesEnabled(True)
        self.host.refresh_status()
        self.list_widget.viewport().update()

    def clear_search(self):
        self.search.clear()
        self.filter_messages()
        self.search.setFocus()

    def search_all(self):
        self.view_category.setCurrentIndex(self.view_category.findData(ALL_CATEGORY))
        self.search.setFocus()

    def filter_messages(self):
        self.search_timer.stop()
        if self._suspended_state is not None:
            return
        query = self.search.text().strip().casefold()
        cid = self.view_category.currentData() or ALL_CATEGORY
        self.list_widget.itemDelegate().set_show_categories(cid == ALL_CATEGORY)
        category_rows = set(self.host.messages.rows_for(cid))
        visible = []
        self.list_widget.setUpdatesEnabled(False)
        try:
            for row, (_, text) in enumerate(self.host.messages.iter_messages()):
                matches = row in category_rows and (not query or query in text.casefold())
                self.list_widget.item(row).setHidden(not matches)
                if matches:
                    visible.append(row)
            current = self.list_widget.currentRow()
            if current not in visible:
                selected = self.selected_rows()
                if selected:
                    self.list_widget.setCurrentItem(self.list_widget.item(selected[0]), QItemSelectionModel.SelectionFlag.NoUpdate)
                else:
                    self.list_widget.setCurrentRow(visible[0] if visible else -1)
        finally:
            self.list_widget.setUpdatesEnabled(True)
        count = len(category_rows)
        self.count_label.setText(f"{len(visible)} / {count} 条" if query else f"{count} 条")
        if query and not visible:
            scope = self.host.messages.category_name(cid)
            self.no_matches.setText(f"在「{scope}」中找不到匹配消息。")
            self.search_all_button.setVisible(cid != ALL_CATEGORY)
        self.message_stack.setCurrentIndex(0 if visible else 2 if query else 1)
        self.update_actions()

    def change(self, action, row=None):
        if self.import_worker is not None or self.host.closing:
            return False
        try:
            if self.host.sender.edit(action) is False:
                self.host.result_label.setText("内容未变化，未重复保存，发送进度保持不变。")
                return False
            self.reload_messages(row)
            self.host.result_label.setText("已自动保存。修改消息会重置受影响类别和全部消息的进度；其他类别保留进度。")
            return True
        except (OSError, ValueError) as exc:
            self.host.error(exc)
            return False

    def add_message(self):
        if self.import_worker is not None or self.host.closing:
            return
        cid = self.view_category.currentData()
        if cid == ALL_CATEGORY:
            cid = UNCATEGORIZED
        dialog = MessageDialog(self, "添加消息", category_options=self.host.messages.categories,
                               selected_category=cid, confirm_text="添加消息")
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        text = dialog.input.text().strip()
        cid = dialog.category.currentData()
        dialog.deleteLater()
        if accepted:
            if self.change(lambda: self.host.messages.append([text], cid), self.host.messages.count):
                self.host.result_label.setText(f"消息已添加到“{self.host.messages.category_name(cid)}”。发送范围保持当前勾选。")

    def edit_message(self, *_):
        if self.import_worker is not None or self.host.closing:
            return
        row = self.list_widget.currentRow()
        if row < 0:
            return
        category = self.host.messages.category_name(self.host.messages.category_for(row))
        dialog = MessageDialog(self, "编辑消息", self.host.messages.text_at(row), row,
                               hint=f"所属类别：{category}\n内容变化并保存后，受影响类别和全部消息从第一条开始。",
                               confirm_text="保存消息")
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        text = dialog.input.text().strip()
        dialog.deleteLater()
        if accepted:
            self.change(lambda: self.host.messages.edit_message(row, text), row)

    def delete_message(self):
        rows = self.selected_rows()
        if not rows:
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("删除消息")
        dialog.setText(f"确定删除选中的 {len(rows)} 条消息？")
        preview = "\n".join(f"第 {row + 1:02d} 条：{self.host.messages.text_at(row)[:120]}" for row in rows[:5])
        if len(rows) > 5:
            preview += f"\n另有 {len(rows) - 5} 条。"
        dialog.setInformativeText(preview + "\n删除后自动保存，无法撤销；受影响类别和全部消息从第一条开始。")
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText("删除")
        dialog.button(QMessageBox.StandardButton.No).setText("取消")
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        style_message_box(dialog, QMessageBox.StandardButton.Yes)
        answer = dialog.exec()
        dialog.deleteLater()
        if answer == QMessageBox.StandardButton.Yes:
            self.change(lambda: self.host.messages.delete_messages(rows), rows[0])

    def clear_messages(self):
        cid = self.view_category.currentData() or ALL_CATEGORY
        rows = self.host.messages.rows_for(cid)
        count = len(rows)
        if not count:
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("清空消息列表")
        dialog.setText(f"确定删除列表中的全部 {count} 条消息？" if cid == ALL_CATEGORY
                       else f"确定清空“{self.host.messages.category_name(cid)}”中的全部 {count} 条消息？")
        dialog.setInformativeText("清空后会自动保存，无法直接撤销。如需保留，请先取消并备份消息库。")
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText("清空列表")
        dialog.button(QMessageBox.StandardButton.No).setText("取消")
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.setEscapeButton(QMessageBox.StandardButton.No)
        style_message_box(dialog, QMessageBox.StandardButton.Yes)
        answer = dialog.exec()
        dialog.deleteLater()
        if answer == QMessageBox.StandardButton.Yes:
            self.change(lambda: self.host.messages.delete_messages(rows))

    def move(self, direction):
        row = self.list_widget.currentRow()
        rows = self.host.messages.rows_for(self.view_category.currentData() or ALL_CATEGORY)
        offset = rows.index(row) if row in rows else -1
        if offset >= 0 and 0 <= offset + direction < len(rows):
            target = rows[offset + direction]
            self.change(lambda: self.host.messages.swap(row, target), target)

    def import_txt(self):
        if self.import_worker is not None or self.host.closing:
            return
        path, _ = QFileDialog.getOpenFileName(self, "导入 TXT（追加到列表）", "", "文本文件 (*.txt)")
        if path:
            self.import_category = self.view_category.currentData() or UNCATEGORIZED
            self.import_worker = ImportWorker(Path(path), tuple(self.host.messages.messages), self)
            self.import_worker.finished.connect(self._import_prepared)
            self.host.result_label.setText("正在读取并检查导入文件…")
            self.update_actions()
            self.import_worker.start()

    def cancel_import(self):
        if self.import_worker is not None:
            self.import_worker.cancel.set()
            self.cancel_import_button.setEnabled(False)
            self.host.result_label.setText("正在取消导入…")

    @Slot()
    def _import_prepared(self):
        worker = self.import_worker
        if worker is None:
            return
        try:
            if self.host.closing:
                return
            if worker.cancel.is_set():
                self.host.result_label.setText("已取消导入，现有消息未更改。")
                return
            if worker.error:
                self.host.error(worker.error)
                self.host.result_label.setText("导入未完成，现有消息未更改。")
                return
            # Keep the import guard until the modal preview has closed too.
            preview = worker.preview
            destination = UNCATEGORIZED if self.import_category == ALL_CATEGORY else self.import_category
            dialog = ImportDialog(self, preview, self.host.messages.categories, destination)
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            destination = dialog.destination.currentData()
            skip_duplicates = dialog.skip_duplicates.isChecked()
            dialog.deleteLater()
        finally:
            self.import_worker = None
            worker.deleteLater()
            self.update_actions()
        if accepted and not self.host.closing:
            try:
                def append():
                    # Recompute inside the same edit lock as persistence, using
                    # all input lines rather than the preview's old unique subset.
                    incoming = (deduplicate_messages(preview.messages, self.host.messages.messages)
                                if skip_duplicates else preview.messages)
                    if not incoming:
                        return False
                    self.host.messages.append(incoming, destination)
                    return True
                row = self.host.messages.count
                if self.host.sender.edit(append):
                    self.reload_messages(row)
                    name = self.host.messages.category_name(destination)
                    self.host.result_label.setText(f"已追加到「{name}」，该类别和全部消息的发送进度已重置。")
                else:
                    self.host.result_label.setText("没有需要追加的新消息，现有消息和发送进度未更改。")
            except (OSError, ValueError) as exc:
                self.host.error(exc)
        else:
            self.host.result_label.setText("已取消导入，现有消息未更改。")

    def export_txt(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出 TXT", "messages.txt", "文本文件 (*.txt)")
        if path:
            try:
                self.host.messages.export_txt(Path(path), self.view_category.currentData() or ALL_CATEGORY)
                self.host.result_label.setText(f"已导出到 {path}")
            except (OSError, ValueError) as exc:
                self.host.error(exc)

    def export_backup(self):
        if not self.can_edit():
            return
        path, _ = QFileDialog.getSaveFileName(self, "备份消息库", "messages-backup.json", "JSON 文件 (*.json)")
        if not path or self.host.closing:
            return
        try:
            destination = Path(path)
            resolved = destination.resolve()
            data_files = (self.host.messages.path, self.host.config.path, self.host.updater.preferences_path)
            if any(resolved == file.resolve() for file in data_files):
                raise ValueError("请选择其他文件名，避免覆盖程序的本地数据文件。")
            self.host.messages.export_backup(destination)
            self.host.result_label.setText(f"消息库已备份到 {destination}")
        except (OSError, ValueError, RuntimeError) as exc:
            self.host.error(exc)

    def restore_backup(self):
        if not self.can_edit():
            return
        path, _ = QFileDialog.getOpenFileName(self, "恢复消息库", "", "JSON 文件 (*.json)")
        if not path or self.host.closing:
            return
        try:
            library = self.host.messages.read_backup(Path(path))
        except (OSError, ValueError, RecursionError) as exc:
            self.host.error(f"无法读取消息库备份。\n{exc}")
            return

        current = self.host.messages
        dialog = RestoreBackupDialog(self, Path(path).name,
                                     (len(current.categories) - 1, current.count),
                                     (len(library["categories"]) - 1, len(library["messages"])))
        answer = dialog.exec()
        dialog.deleteLater()
        if answer != QDialog.DialogCode.Accepted or self.host.closing or self.import_worker is not None:
            return
        try:
            backup = self.host.sender.edit(lambda: self.host.messages.restore_backup(library))
        except (OSError, ValueError) as exc:
            self.host.error(f"恢复失败。\n{exc}")
            return
        if backup is None:
            self.host.result_label.setText("备份与当前消息库一致，无需恢复。")
            return
        self.reload_messages()
        self.host.result_label.setText("消息库已恢复，发送进度已重置。恢复前的备份已保存到本地数据文件夹。")


class RestoreBackupDialog(QDialog):
    def __init__(self, parent, filename, current, incoming):
        super().__init__(parent)
        self.setWindowTitle("恢复消息库")
        self.setWindowIcon(parent.windowIcon())
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        layout.addWidget(label("恢复消息库", "section"))
        source = ElidingLabel("muted")
        source.set_full_text(f"备份文件  {filename}")
        layout.addWidget(source)
        comparison = QHBoxLayout()
        for heading, (categories, messages) in (("当前消息库", current), ("恢复后", incoming)):
            panel = Panel()
            values = QVBoxLayout(panel)
            values.setContentsMargins(13, 11, 13, 11)
            values.addWidget(label(heading, "muted"))
            values.addWidget(label(f"{categories} 个自建类别 · {messages} 条", "progress", True))
            comparison.addWidget(panel, 1)
            if heading == "当前消息库":
                comparison.addWidget(label("→", "muted"))
        layout.addLayout(comparison)
        warning = label("当前消息库将被覆盖，发送类别的勾选和顺序也会恢复。", wrap=True)
        warning.setStyleSheet("color: #e9bd75;")
        layout.addWidget(warning)
        layout.addWidget(label("覆盖前会自动备份当前消息库到本地数据文件夹。", "muted", True))
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = CutButton("取消")
        cancel.setDefault(True)
        cancel.clicked.connect(self.reject)
        confirm = CutButton("覆盖并恢复", primary=True)
        confirm.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(confirm)
        layout.addLayout(actions)
        cancel.setFocus()

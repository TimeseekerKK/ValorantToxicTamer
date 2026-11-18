"""Incremental edits preserve identity, selections, scheduling and atomicity."""
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QStyleOptionViewItem

from valorant_toxic_tamer.config_manager import ConfigManager
from valorant_toxic_tamer.diagnostics import configure_logging
from valorant_toxic_tamer.message_manager import MessageManager, ALL_CATEGORY, validate_library
from valorant_toxic_tamer.sender import Sender
from valorant_toxic_tamer.ui import MainWindow


class IncrementalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        root = Path(self.temp.name)
        self.messages = MessageManager(root / "messages.json")
        self.messages.replace([f"消息 {i:03d}" for i in range(120)])
        self.config = ConfigManager(root / "config.json")
        self.sender = Sender(self.messages, Mock())
        self.window = MainWindow(self.messages, self.config, self.sender, self.config.save)
        self.window.error = Mock()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.shutdown()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_edit_preserves_unrelated_items_selection_and_scroll(self):
        widget = self.window.management.list_widget
        first, selected = widget.item(0), widget.item(60)
        widget.setCurrentRow(60)
        widget.item(61).setSelected(True)
        widget.scrollToItem(selected)
        self.app.processEvents()
        scroll = widget.verticalScrollBar().value()
        keys = {self.messages.key_at(row) for row in (60, 61)}
        self.window.management.change(lambda: self.messages.edit_message(60, "修改后的消息"))
        self.app.processEvents()
        self.assertIs(widget.item(0), first)
        self.assertIs(widget.item(60), selected)
        self.assertEqual(self.window.management.selected_rows(), [60, 61])
        self.assertEqual({item.data(Qt.ItemDataRole.UserRole + 1) for item in widget.selectedItems()}, keys)
        self.assertEqual(widget.verticalScrollBar().value(), scroll)
        self.assertEqual(widget.item(60).data(Qt.ItemDataRole.UserRole), "修改后的消息")
        self.assertEqual(MessageManager(self.messages.path).text_at(60), "修改后的消息")

    def test_category_selection_reuses_controls_and_does_not_rebuild_message_index(self):
        cid = self.messages.create_category("类别")
        self.window.reload_messages()
        first = self.window.management.send_categories.item(0)
        second = self.window.management.send_categories.item(1)
        self.messages.advance()
        positions = self.messages._positions.copy()
        with patch.object(self.messages, "_rebuild") as rebuild:
            self.messages.select_categories([cid])
            self.window.management.sync_categories()
            rebuild.assert_not_called()
        self.assertIs(self.window.management.send_categories.item(0), first)
        self.assertIs(self.window.management.send_categories.item(1), second)
        self.assertEqual(self.messages._positions, positions)
        self.assertEqual(MessageManager(self.messages.path).selected_categories, [cid])

    def test_failed_edits_never_mutate_shared_entries_or_progress(self):
        cid = self.messages.create_category("类别")
        self.messages.advance()
        before = self.messages.path.read_bytes()
        keys = list(self.messages.iter_messages())
        for action in (lambda: self.messages.edit_message(0, "修改"),
                       lambda: self.messages.move_to_category([0, 1], cid),
                       lambda: self.messages.delete_messages([0, 1]),
                       lambda: self.messages.rename_category(cid, "改名")):
            with self.subTest(action=action), patch("valorant_toxic_tamer.message_manager.atomic_json", side_effect=OSError("full")):
                with self.assertRaises(OSError):
                    action()
            self.assertEqual(self.messages.path.read_bytes(), before)
            self.assertEqual(list(self.messages.iter_messages()), keys)
            self.assertEqual(self.messages.position, 1)
        validate_library(json.loads(before))

    def test_changed_text_is_validated_and_invalid_input_never_saved(self):
        before = self.messages.path.read_bytes()
        for action in (lambda: self.messages.edit_message(0, "bad\ntext"),
                       lambda: self.messages.append(["bad\ttext"]),
                       lambda: self.messages.append(["good"], "missing")):
            with self.assertRaises(ValueError):
                action()
            self.assertEqual(self.messages.path.read_bytes(), before)

    def test_bulk_delete_only_visible_selected_messages_and_keeps_other_items(self):
        widget = self.window.management.list_widget
        widget.setCurrentRow(10)
        widget.item(11).setSelected(True)
        widget.item(20).setSelected(True)
        self.window.management.search.setText("01")
        self.window.management.filter_messages()
        widget.item(10).setSelected(True)
        widget.item(11).setSelected(True)
        retained = widget.item(30)
        observed = []
        def confirm(dialog):
            observed.append(dialog.text())
            return QMessageBox.StandardButton.Yes
        with patch.object(QMessageBox, "exec", confirm):
            self.window.management.delete_message()
        self.assertIn("2 条消息", observed[0])
        self.assertEqual(self.messages.count, 118)
        self.assertNotIn("消息 010", self.messages.messages)
        self.assertIn("消息 020", self.messages.messages)
        self.assertIs(widget.item(28), retained)
        self.assertEqual(retained.text(), "29   消息 030")
        self.assertEqual(MessageManager(self.messages.path).messages, self.messages.messages)

    def test_layout_cache_invalidates_on_text_width_and_font(self):
        delegate = self.window.management.list_widget.itemDelegate()
        index = self.window.management.list_widget.model().index(0, 0)
        option = QStyleOptionViewItem()
        first = delegate.sizeHint(option, index)
        self.assertEqual(delegate.sizeHint(option, index), first)
        self.window.management.change(lambda: self.messages.edit_message(0, "长消息" * 200))
        self.assertGreater(delegate.sizeHint(option, index).height(), first.height())
        self.window.resize(840, 638)
        self.app.processEvents()
        narrow = delegate.sizeHint(option, index)
        self.config.value["font_size"] = 16
        self.window.apply_font_size()
        self.app.processEvents()
        self.assertGreaterEqual(delegate.sizeHint(option, index).height(), narrow.height())

    def test_log_creation_failure_returns_a_safe_handler(self):
        with patch("valorant_toxic_tamer.diagnostics.RotatingFileHandler", side_effect=OSError("denied")):
            handler = configure_logging(self.messages.path.parent)
        try:
            self.assertIsInstance(handler, logging.NullHandler)
            self.assertIn("denied", handler.startup_error)
            logging.getLogger("ValorantToxicTamer").info("core still running")
        finally:
            logging.getLogger("ValorantToxicTamer").removeHandler(handler)
            handler.close()

"""Category scheduling, safe migration and UI integration; no real game input."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QScrollArea

from valorant_toxic_tamer.config_manager import ConfigManager, DEFAULT_CONFIG
from valorant_toxic_tamer.message_manager import ALL_CATEGORY, UNCATEGORIZED, MessageManager
from valorant_toxic_tamer.sender import Sender
from valorant_toxic_tamer.ui import MainWindow, ImportDialog
from valorant_toxic_tamer.ui_theme import MessageDialog
from test_core import FakeAPI


class CategoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.messages = MessageManager(self.root / "messages.json")
        self.a = self.messages.create_category("鼓励")
        self.b = self.messages.create_category("战术")
        self.empty = self.messages.create_category("空类别")
        self.messages.append(["A1", "A2", "A3"], self.a)
        self.messages.append(["B1", "B2"], self.b)

    def take(self, count):
        result = []
        for _ in range(count):
            result.append(self.messages.current)
            self.messages.advance()
        return result

    def test_sequential_click_order_and_wrap_with_empty_categories(self):
        self.messages.select_categories([self.empty, self.b, self.a])
        self.assertEqual(self.take(7), ["B1", "B2", "A1", "A2", "A3", "B1", "B2"])

    def test_alternating_click_order_and_unequal_lengths(self):
        self.messages.select_categories([self.b, self.empty, self.a])
        self.messages.set_mode("alternating")
        self.assertEqual(self.take(8), ["B1", "A1", "B2", "A2", "B1", "A3", "B2", "A1"])

    def test_switching_mode_preserves_positions_and_restarts_category_order(self):
        self.messages.select_categories([self.a, self.b])
        self.take(4)
        self.messages.set_mode("alternating")
        self.assertEqual(self.take(3), ["A1", "B2", "A2"])

    def test_switching_preserves_each_category_progress(self):
        self.messages.select_categories([self.a])
        self.take(2)
        self.messages.select_categories([self.b])
        self.take(1)
        self.messages.select_categories([self.a, self.b])
        self.assertEqual(self.take(3), ["A3", "B2", "A1"])

    def test_all_progress_is_independent_in_both_directions(self):
        self.take(1)
        self.messages.select_categories([self.a])
        self.assertEqual(self.messages.current, "A1")
        self.take(2)
        self.messages.select_categories([ALL_CATEGORY])
        self.assertEqual(self.messages.current, "A2")
        self.take(2)
        self.messages.select_categories([self.a])
        self.assertEqual(self.messages.current, "A3")

    def test_selection_persists_but_progress_resets_on_restart(self):
        self.messages.select_categories([self.b, self.a])
        self.take(1)
        restored = MessageManager(self.messages.path)
        self.assertEqual(restored.selected_categories, [self.b, self.a])
        self.assertEqual(restored.current, "B1")

    def test_empty_selection_and_empty_categories_do_not_fall_back_to_all(self):
        for selection in ([], [self.empty]):
            self.messages.select_categories(selection)
            api = FakeAPI()
            sender = Sender(self.messages, api)
            self.assertFalse(sender.trigger("team"))
            self.assertEqual(api.events, [])
            self.assertIsNone(self.messages.current)
            self.messages.advance()

    def test_invalid_selection_is_atomic(self):
        before = self.messages.path.read_bytes()
        for selected in ([ALL_CATEGORY, self.a], [self.a, self.a], ["missing"]):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                self.messages.select_categories(selected)
        self.assertEqual(before, self.messages.path.read_bytes())
        self.assertEqual(self.messages.selected_categories, [ALL_CATEGORY])

    def test_delete_category_retains_messages_and_other_category_progress(self):
        self.messages.select_categories([self.b])
        self.take(1)
        self.messages.delete_category(self.a)
        self.assertEqual(self.messages.current, "B2")
        self.assertEqual(self.messages.messages, ["A1", "A2", "A3", "B1", "B2"])
        self.assertEqual(self.messages.rows_for(UNCATEGORIZED), [0, 1, 2])
        self.messages.delete_category(self.b)
        self.assertEqual(self.messages.selected_categories, [])
        self.assertIsNone(self.messages.current)
        self.assertEqual(len(MessageManager(self.messages.path).messages), 5)

    def test_reserved_empty_control_and_duplicate_names_are_rejected(self):
        for name in ("", "全部消息", "未分类", "鼓励", "a\tb", "x" * 41):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.messages.create_category(name)
        for cid in (ALL_CATEGORY, UNCATEGORIZED):
            with self.assertRaises(ValueError):
                self.messages.delete_category(cid)
            with self.assertRaises(ValueError):
                self.messages.rename_category(cid, "新名称")

    def test_rename_preserves_selection_and_progress(self):
        self.messages.select_categories([self.a])
        self.take(1)
        self.messages.rename_category(self.a, "友好交流")
        self.assertEqual(self.messages.current, "A2")
        self.assertEqual(self.messages.selected_categories, [self.a])
        self.assertEqual(self.messages.category_name(self.a), "友好交流")

    def test_batch_assignment_preserves_text_order_and_unaffected_progress(self):
        self.messages.select_categories([self.b])
        self.take(1)
        self.messages.move_to_category([0, 2], self.empty)
        self.assertEqual(self.messages.current, "B2")
        self.assertEqual(self.messages.rows_for(self.empty), [0, 2])
        self.assertEqual(self.messages.rows_for(self.a), [1])
        restored = MessageManager(self.messages.path)
        self.assertEqual(restored.messages, self.messages.messages)
        self.assertEqual(restored.rows_for(self.empty), [0, 2])

    def test_edit_import_and_reorder_keep_category_membership(self):
        self.messages.edit_message(0, "修改后的A1")
        self.messages.swap(0, 2)
        self.messages.append(["A4"], self.a)
        self.assertEqual(self.messages.rows_for(self.a), [0, 1, 2, 5])
        self.messages.select_categories([self.a])
        self.assertEqual(self.take(4), ["A3", "A2", "修改后的A1", "A4"])

    def test_saving_failure_preserves_file_selection_content_and_progress(self):
        self.messages.select_categories([self.a])
        self.take(1)
        before = self.messages.path.read_bytes()
        with patch("valorant_toxic_tamer.message_manager.atomic_json", side_effect=OSError("disk full")):
            for operation in (lambda: self.messages.select_categories([self.b]),
                              lambda: self.messages.move_to_category([0], self.b),
                              lambda: self.messages.delete_category(self.a)):
                with self.assertRaises(OSError):
                    operation()
                self.assertEqual(self.messages.path.read_bytes(), before)
                self.assertEqual(self.messages.current, "A2")
                self.assertEqual(self.messages.selected_categories, [self.a])

    def test_legacy_load_is_read_only_and_first_edit_backs_up_exact_bytes(self):
        path = self.root / "legacy.json"
        original = b'\xef\xbb\xbf["old", "same", "same"]\r\n'
        path.write_bytes(original)
        manager = MessageManager(path)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(manager.rows_for(UNCATEGORIZED), [0, 1, 2])
        manager.create_category("新类别")
        backups = list(self.root.glob("legacy.legacy-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertEqual(MessageManager(path).messages, ["old", "same", "same"])
        manager.append(["new"])
        self.assertEqual(len(list(self.root.glob("legacy.legacy-*.json"))), 1)

    def test_failed_legacy_backup_prevents_migration(self):
        path = self.root / "legacy.json"
        path.write_text('["old"]', encoding="utf-8")
        manager = MessageManager(path)
        original = path.read_bytes()
        with patch("valorant_toxic_tamer.message_manager.os.fsync", side_effect=OSError("backup failed")):
            with self.assertRaises(OSError):
                manager.append(["new"])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(manager.messages, ["old"])

    def test_corrupt_category_file_is_preserved(self):
        library = json.loads(self.messages.path.read_text(encoding="utf-8"))
        library["messages"][0]["category"] = "missing"
        self.messages.path.write_text(json.dumps(library), encoding="utf-8")
        before = self.messages.path.read_bytes()
        with self.assertRaises(ValueError):
            MessageManager(self.messages.path)
        self.assertEqual(before, self.messages.path.read_bytes())

    def test_export_only_requested_category(self):
        path = self.root / "export.txt"
        self.messages.export_txt(path, self.b)
        self.assertEqual(path.read_text(encoding="utf-8-sig"), "B1\nB2\n")

    def test_channels_share_category_schedule_and_failed_input_does_not_advance(self):
        self.messages.select_categories([self.b, self.a])
        self.messages.set_mode("alternating")
        api = FakeAPI()
        sender = Sender(self.messages, api, cooldown=0.5, clock=lambda: 100, wait=lambda _: None)
        self.addCleanup(sender.stop)
        self.assertTrue(sender.trigger("team"))
        sender.thread.join(2)
        self.assertEqual(self.messages.current, "A1")
        sender.ready_at = 0
        api.fail_text = True
        self.assertTrue(sender.trigger("all"))
        sender.thread.join(2)
        self.assertEqual(self.messages.current, "A1")
        sender.ready_at = 0
        api.fail_text = False
        self.assertTrue(sender.trigger("all"))
        sender.thread.join(2)
        self.assertEqual(self.messages.current, "B2")

    def test_old_config_without_new_optional_fields_loads_without_writing(self):
        path = self.root / "config.json"
        value = {k: v for k, v in DEFAULT_CONFIG.items() if k not in ("category_mode", "font_size")}
        path.write_text(json.dumps(value), encoding="utf-8")
        before = path.read_bytes()
        config = ConfigManager(path)
        self.assertEqual(config.value, DEFAULT_CONFIG)
        self.assertEqual(before, path.read_bytes())


class CategoryUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.messages = MessageManager(self.root / "messages.json")
        self.a = self.messages.create_category("鼓励")
        self.b = self.messages.create_category("战术")
        self.messages.append(["A1", "A2"], self.a)
        self.messages.append(["B1", "B2"], self.b)
        self.config = ConfigManager(self.root / "config.json")
        self.sender = Sender(self.messages, Mock())
        self.window = MainWindow(self.messages, self.config, self.sender, self.config.save)
        self.window.error = Mock()

    def tearDown(self):
        self.window.shutdown()
        self.sender.stop()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def check(self, cid, checked=True):
        item = next(self.window.send_categories.item(i) for i in range(self.window.send_categories.count())
                    if self.window.send_categories.item(i).data(Qt.ItemDataRole.UserRole) == cid)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def view(self, cid):
        self.window.view_category.setCurrentIndex(self.window.view_category.findData(cid))

    def test_check_order_all_exclusivity_and_rechecking_moves_to_end(self):
        self.check(self.b)
        self.check(self.a)
        self.assertEqual(self.messages.selected_categories, [self.b, self.a])
        self.assertIn("战术 → 鼓励", self.window.send_order_label.text())
        self.check(self.b, False)
        self.check(self.b)
        self.assertEqual(self.messages.selected_categories, [self.a, self.b])
        self.check(ALL_CATEGORY)
        self.assertEqual(self.messages.selected_categories, [ALL_CATEGORY])

    def test_view_and_search_do_not_change_sending_selection_or_progress(self):
        self.check(self.a)
        self.messages.advance()
        before = self.messages.path.read_bytes()
        self.view(self.b)
        self.window.search.setText("B2")
        self.window.filter_messages()
        self.assertEqual(self.window.count_label.text(), "1 / 2 条")
        self.assertEqual(self.window.list_widget.currentRow(), 3)
        self.assertEqual(self.messages.current, "A2")
        self.assertEqual(self.messages.selected_categories, [self.a])
        self.assertEqual(self.messages.path.read_bytes(), before)

    def test_batch_move_uses_visible_selected_rows_and_keeps_text(self):
        self.view(self.a)
        self.window.list_widget.item(1).setSelected(True)
        self.window.move_category.setCurrentIndex(self.window.move_category.findData(self.b))
        self.window.assign_category()
        self.assertEqual(self.messages.rows_for(self.b), [0, 1, 2, 3])
        self.assertEqual(self.messages.messages, ["A1", "A2", "B1", "B2"])
        self.assertEqual(self.window.count_label.text(), "0 条")

    def test_add_in_view_goes_to_viewed_category(self):
        self.view(self.b)
        def confirm(dialog):
            dialog.input.setText("B3")
            return QDialog.DialogCode.Accepted
        with patch.object(MessageDialog, "exec", confirm):
            self.window.add_message()
        self.assertEqual(self.messages.category_for(4), self.b)
        self.assertEqual(self.messages.selected_categories, [ALL_CATEGORY])

    def test_clearing_view_only_deletes_that_category(self):
        self.view(self.b)
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes):
            self.window.clear_messages()
        self.assertEqual(self.messages.messages, ["A1", "A2"])
        self.assertEqual(self.messages.rows_for(self.a), [0, 1])

    def test_reorder_in_category_skips_other_categories(self):
        self.messages.swap(1, 2)
        self.window.reload_messages()
        self.view(self.a)
        self.window.list_widget.setCurrentRow(0)
        self.window.move(1)
        self.assertEqual(self.messages.messages, ["A2", "B1", "A1", "B2"])
        self.assertEqual(self.messages.category_for(1), self.b)

    def test_save_mode_changes_runtime_and_survives_restart(self):
        self.window.ensure_settings()
        self.window.category_mode.setCurrentIndex(self.window.category_mode.findData("alternating"))
        self.assertIn("未保存", self.window.settings_hint.text())
        self.window.apply_settings()
        self.assertEqual(self.messages.mode, "alternating")
        self.assertEqual(ConfigManager(self.config.path).value["category_mode"], "alternating")

    def test_busy_prevents_selection_mutation_and_restores_checkbox(self):
        self.sender.busy = True
        before = self.messages.path.read_bytes()
        self.check(self.a)
        self.window.refresh_status()
        self.window.error.assert_called_once()
        self.assertEqual(before, self.messages.path.read_bytes())
        self.assertEqual(self.messages.selected_categories, [ALL_CATEGORY])
        self.assertFalse(self.window.send_categories.isEnabled())
        self.sender.busy = False

    def test_import_goes_to_viewed_category_and_preserves_other_membership(self):
        source = self.root / "import.txt"
        source.write_text("新增战术\nB1", encoding="utf-8")
        self.view(self.b)
        with patch("valorant_toxic_tamer.ui.QFileDialog.getOpenFileName", return_value=(str(source), "")), \
                patch.object(ImportDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            self.window.import_txt()
            for _ in range(500):
                if self.window.import_worker is None:
                    break
                QTest.qWait(10)
        self.assertIsNone(self.window.import_worker)
        self.window.error.assert_not_called()
        self.assertEqual(self.messages.rows_for(self.a), [0, 1])
        self.assertEqual(self.messages.rows_for(self.b), [2, 3, 4, 5])
        self.assertEqual(self.messages.messages[-2:], ["新增战术", "B1"])

    def test_category_dialogs_and_delete_keep_messages(self):
        def confirm(dialog):
            self.assertEqual(dialog.input.accessibleName(), "类别名称")
            dialog.input.setText("新类别")
            return QDialog.DialogCode.Accepted
        with patch.object(MessageDialog, "exec", confirm):
            self.window.create_category()
        cid = self.window.view_category.currentData()
        self.assertEqual(self.messages.category_name(cid), "新类别")
        self.assertNotIn(cid, self.messages.selected_categories)
        self.view(self.a)
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes):
            self.window.delete_category()
        self.assertEqual(self.messages.messages, ["A1", "A2", "B1", "B2"])
        self.assertEqual(self.messages.rows_for(UNCATEGORIZED), [0, 1])

    def test_new_controls_fit_at_minimum_size_and_largest_font(self):
        self.config.save({**self.config.value, "font_size": 16})
        self.window.apply_font_size()
        self.window.resize(840, 638)
        self.window.show()
        self.app.processEvents()
        for widget in (self.window.view_category, self.window.create_category_button,
                       self.window.rename_category_button, self.window.delete_category_button,
                       self.window.move_category, self.window.assign_category_button):
            self.assertTrue(widget.parentWidget().rect().contains(widget.geometry()))
        self.window.tabs.setCurrentIndex(1)
        self.app.processEvents()
        scroll = self.window.tabs.widget(1).findChild(QScrollArea)
        scroll.ensureWidgetVisible(self.window.category_mode)
        self.app.processEvents()
        self.assertTrue(scroll.viewport().rect().contains(
            self.window.category_mode.mapTo(scroll.viewport(), self.window.category_mode.rect().bottomRight())))

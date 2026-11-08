"""Search/import contracts; temporary data, no game input or networking."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from valorant_toxic_tamer.config_manager import ConfigManager
from valorant_toxic_tamer.message_manager import MessageManager, prepare_txt_import
from valorant_toxic_tamer.sender import Sender
from valorant_toxic_tamer.ui import ImportDialog, MainWindow
from valorant_toxic_tamer.ui_theme import MessageDialog


class MessageFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        for name in ("msyh.ttc", "segoeui.ttf"):
            font = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts" / name
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.messages = MessageManager(self.root / "messages.json")
        self.messages.replace(["第一条 Alpha", "第二条 Bravo", "第三条 Alpha"])
        self.config = ConfigManager(self.root / "config.json")
        self.sender = Sender(self.messages, Mock())
        self.window = MainWindow(self.messages, self.config, self.sender, self.config.save)
        self.window.error = Mock()
        self.source = self.root / "import.txt"

    def tearDown(self):
        self.window.shutdown()
        self.sender.stop()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def wait_until(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate())

    def test_search_preserves_real_rows_index_and_saved_messages(self):
        self.messages.advance()
        before = self.messages.path.read_bytes()
        self.window.search.setText("ALPHA")
        self.wait_until(lambda: self.window.list_widget.item(1).isHidden())
        self.assertFalse(self.window.list_widget.item(2).isHidden())
        self.assertEqual(self.window.count_label.text(), "2 / 3 条")
        self.window.list_widget.setCurrentRow(2)
        self.assertFalse(self.window.up_button.isEnabled())
        self.assertFalse(self.window.down_button.isEnabled())
        self.assertEqual(self.messages.index, 1)
        self.assertEqual(self.messages.path.read_bytes(), before)
        self.assertEqual(self.window.list_widget.currentRow(), 2)

    def test_editing_filtered_result_changes_correct_message(self):
        self.window.search.setText("Bravo")
        self.window.filter_messages()
        self.assertEqual(self.window.list_widget.currentRow(), 1)
        QTimer.singleShot(0, lambda: self._finish_edit("已修改 Bravo"))
        self.window.edit_message()
        self.assertEqual(self.messages.messages, ["第一条 Alpha", "已修改 Bravo", "第三条 Alpha"])
        self.assertEqual(self.window.count_label.text(), "1 / 3 条")

    def _finish_edit(self, text):
        dialog = self.app.activeModalWidget()
        dialog.input.setText(text)
        dialog.accept()

    def test_imported_long_messages_survive_edit_and_save_without_truncation(self):
        for text in ("x" * 40000, "汉😀" * 20000):
            with self.subTest(characters=len(text)):
                self.source.write_text(text, encoding="utf-8")
                self.messages.replace([])
                self.messages.import_txt(self.source)
                self.window.reload_messages()
                def confirm(dialog):
                    self.assertEqual(dialog.input.text(), text)
                    dialog.input.deselect()
                    dialog.input.setCursorPosition(len(text.encode("utf-16-le")) // 2)
                    dialog.input.insert("尾")
                    return QDialog.DialogCode.Accepted
                with patch.object(MessageDialog, "exec", confirm):
                    self.window.edit_message()
                self.assertEqual(self.messages.messages, [text + "尾"])
                self.assertEqual(MessageManager(self.messages.path).messages, [text + "尾"])

    def test_add_dialog_preserves_long_pasted_message(self):
        text = "😀" * 20000
        def confirm(dialog):
            dialog.input.setText(text)
            self.assertEqual(dialog.input.text(), text)
            return QDialog.DialogCode.Accepted
        with patch.object(MessageDialog, "exec", confirm):
            self.window.add_message()
        self.assertEqual(MessageManager(self.messages.path).messages[-1], text)

    def test_no_results_clears_selection_and_clear_search_restores_all(self):
        self.window.search.setText("不存在")
        self.window.filter_messages()
        self.assertEqual(self.window.message_stack.currentIndex(), 2)
        self.assertEqual(self.window.list_widget.currentRow(), -1)
        self.assertFalse(self.window.delete_button.isEnabled())
        self.window.search.clear()
        self.window.filter_messages()
        self.assertEqual(self.window.message_stack.currentIndex(), 0)
        self.assertEqual(self.window.list_widget.currentRow(), 0)
        self.assertTrue(all(not self.window.list_widget.item(i).isHidden() for i in range(3)))

    def test_preview_counts_existing_and_internal_duplicates_without_writing(self):
        before = self.messages.path.read_bytes()
        self.source.write_text("第一条 Alpha\n新增\n新增\n\n另一条\n", encoding="utf-8-sig")
        preview = prepare_txt_import(self.source, self.messages.messages)
        self.assertEqual(preview.duplicate_count, 2)
        self.assertEqual(preview.unique_messages, ("新增", "另一条"))
        self.assertEqual(len(preview.messages), 4)
        self.assertEqual(self.messages.path.read_bytes(), before)
        dialog = ImportDialog(self.window, preview)
        self.assertEqual(len(dialog.selected_messages()), 4)
        dialog.skip_duplicates.setChecked(True)
        self.assertEqual(dialog.selected_messages(), ("新增", "另一条"))
        dialog.deleteLater()

    def test_all_duplicate_preview_prevents_empty_import(self):
        self.source.write_text("第一条 Alpha\n第一条 Alpha", encoding="utf-8")
        dialog = ImportDialog(self.window, prepare_txt_import(self.source, self.messages.messages))
        dialog.skip_duplicates.setChecked(True)
        self.assertFalse(dialog.confirm.isEnabled())
        dialog.deleteLater()

    def test_long_import_preview_scrolls_to_fifth_message_at_largest_font(self):
        self.config.save({**self.config.value, "font_size": 16})
        self.window.apply_font_size()
        self.source.write_text("\n".join(["长消息内容" * 40] * 5), encoding="utf-8")
        dialog = ImportDialog(self.window, prepare_txt_import(self.source))
        dialog.show()
        self.app.processEvents()
        self.assertIn("5. ", dialog.preview_text.text())
        self.assertGreater(dialog.preview_scroll.verticalScrollBar().maximum(), 0)
        self.assertTrue(dialog.rect().contains(dialog.confirm.geometry()))
        self.assertLessEqual(dialog.height(), self.app.primaryScreen().availableGeometry().height())
        dialog.close()
        dialog.deleteLater()

    def test_oversized_or_invalid_import_keeps_existing_file_and_progress(self):
        before = self.messages.path.read_bytes()
        self.messages.advance()
        for content in ("a\tb", "\n\n", "a\n" * 20001):
            self.source.write_text(content, encoding="utf-8")
            with self.subTest(content=content[:15]), self.assertRaises(ValueError):
                prepare_txt_import(self.source, self.messages.messages)
        self.source.write_bytes(b"a" * 9)
        with patch("valorant_toxic_tamer.message_manager.MAX_IMPORT_BYTES", 8), self.assertRaises(ValueError):
            prepare_txt_import(self.source)
        self.assertEqual(self.messages.path.read_bytes(), before)
        self.assertEqual(self.messages.index, 1)

    def _import(self):
        with patch("valorant_toxic_tamer.ui.QFileDialog.getOpenFileName", return_value=(str(self.source), "")):
            self.window.import_txt()

    def test_cancel_preview_preserves_file_and_progress(self):
        self.source.write_text("新消息", encoding="utf-8")
        before = self.messages.path.read_bytes()
        self.messages.advance()
        with patch.object(ImportDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            self._import()
            self.wait_until(lambda: self.window.import_worker is None)
        self.assertEqual(self.messages.path.read_bytes(), before)
        self.assertEqual(self.messages.index, 1)

    def test_confirm_preview_deduplicates_and_persists_once(self):
        self.source.write_text("第一条 Alpha\n新增\n新增", encoding="utf-8")
        def confirm(dialog):
            dialog.skip_duplicates.setChecked(True)
            return QDialog.DialogCode.Accepted
        with patch.object(ImportDialog, "exec", confirm):
            self._import()
            self.wait_until(lambda: self.window.import_worker is None)
        self.assertEqual(self.messages.messages[-1], "新增")
        self.assertEqual(len(self.messages.messages), 4)
        self.assertEqual(MessageManager(self.messages.path).messages, self.messages.messages)

    def test_import_rechecks_sender_after_preview(self):
        self.source.write_text("新消息", encoding="utf-8")
        before = self.messages.path.read_bytes()
        def confirm(dialog):
            self.sender.busy = True
            return QDialog.DialogCode.Accepted
        with patch.object(ImportDialog, "exec", confirm):
            self._import()
            self.wait_until(lambda: self.window.import_worker is None)
        self.sender.busy = False
        self.window.error.assert_called_once()
        self.assertEqual(self.messages.path.read_bytes(), before)

    def test_import_preview_blocks_double_click_changes_and_second_import(self):
        self.source.write_text("新增", encoding="utf-8")
        before = self.messages.path.read_bytes()
        self.messages.advance()
        observed = {}
        def confirm(dialog):
            observed["edit_enabled"] = self.window.edit_button.isEnabled()
            self.window.list_widget.itemDoubleClicked.emit(self.window.list_widget.item(0))
            self.window.change(lambda: self.messages.replace(["不应保存"]))
            self.window.import_txt()
            observed["file"] = self.messages.path.read_bytes()
            return QDialog.DialogCode.Rejected
        with patch.object(ImportDialog, "exec", confirm), \
                patch.object(MessageDialog, "exec") as edit, \
                patch("valorant_toxic_tamer.ui.QFileDialog.getOpenFileName", return_value=(str(self.source), "")) as choose:
            self.window.import_txt()
            self.wait_until(lambda: self.window.import_worker is None)
            edit.assert_not_called()
            choose.assert_called_once()
        self.assertFalse(observed["edit_enabled"])
        self.assertEqual(observed["file"], before)
        self.assertEqual(self.messages.path.read_bytes(), before)
        self.assertEqual(self.messages.index, 1)
        self.assertTrue(self.window.edit_button.isEnabled())

    def test_confirm_import_recomputes_duplicates_from_current_messages(self):
        self.source.write_text("新增\n第一条 Alpha\n新增", encoding="utf-8")
        def confirm(dialog):
            dialog.skip_duplicates.setChecked(True)
            self.messages.replace(["新增", "其他"])
            return QDialog.DialogCode.Accepted
        with patch.object(ImportDialog, "exec", confirm):
            self._import()
            self.wait_until(lambda: self.window.import_worker is None)
        self.assertEqual(self.messages.messages, ["新增", "其他", "第一条 Alpha"])

    def test_confirm_import_with_no_new_messages_preserves_file_and_progress(self):
        self.source.write_text("新增", encoding="utf-8")
        snapshot = {}
        def confirm(dialog):
            dialog.skip_duplicates.setChecked(True)
            self.messages.replace(["新增", "其他"])
            self.messages.advance()
            snapshot["file"] = self.messages.path.read_bytes()
            return QDialog.DialogCode.Accepted
        with patch.object(ImportDialog, "exec", confirm):
            self._import()
            self.wait_until(lambda: self.window.import_worker is None)
        self.assertEqual(self.messages.path.read_bytes(), snapshot["file"])
        self.assertEqual(self.messages.index, 1)

    def test_background_parse_keeps_ui_responsive_and_shutdown_does_not_import(self):
        entered, unblock = threading.Event(), threading.Event()
        self.source.write_text("新消息", encoding="utf-8")
        original = prepare_txt_import
        def slow(*args):
            entered.set()
            unblock.wait(3)
            return original(*args)
        with patch("valorant_toxic_tamer.ui.prepare_txt_import", side_effect=slow), \
                patch.object(ImportDialog, "exec") as dialog, \
                patch.object(MessageDialog, "exec") as edit:
            self._import()
            try:
                self.assertTrue(entered.wait(1))
                ticks = []
                QTimer.singleShot(0, lambda: ticks.append(True))
                QTest.qWait(20)
                self.assertTrue(ticks)
                self.assertFalse(self.window.add_button.isEnabled())
                self.assertFalse(self.window.import_button.isEnabled())
                before = self.messages.path.read_bytes()
                self.window.list_widget.itemDoubleClicked.emit(self.window.list_widget.item(0))
                self.window.change(lambda: self.messages.replace(["不应保存"]))
                edit.assert_not_called()
                self.assertEqual(self.messages.path.read_bytes(), before)
            finally:
                unblock.set()
            self.window.shutdown()
            self.app.processEvents()
            dialog.assert_not_called()
        self.assertEqual(len(self.messages.messages), 3)

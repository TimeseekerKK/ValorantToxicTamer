"""Hidden UI releases disposable list data without changing sending or drafts."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from valorant_toxic_tamer.config_manager import ConfigManager
from valorant_toxic_tamer.message_manager import MessageManager
from valorant_toxic_tamer.sender import Sender
from valorant_toxic_tamer.ui import MainWindow


class BackgroundMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        root = Path(self.temp.name)
        self.messages = MessageManager(root / "messages.json")
        self.messages.replace([f"消息 {i:04d}" for i in range(300)])
        self.config = ConfigManager(root / "config.json")
        self.sender = Sender(self.messages, Mock())
        self.window = MainWindow(self.messages, self.config, self.sender, self.config.save)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.shutdown()
        self.sender.stop()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def wait_for_release(self):
        self.window.background_timer.setInterval(10)
        self.window.close()
        QTest.qWait(100)

    def test_hide_releases_rendering_but_preserves_draft_filter_selection_and_progress(self):
        page = self.window.management
        page.search.setText("01")
        page.filter_messages()
        page.list_widget.setCurrentRow(150)
        page.list_widget.item(151).setSelected(True)
        page.list_widget.scrollToItem(page.list_widget.item(150))
        self.app.processEvents()
        scroll = page.list_widget.verticalScrollBar().value()
        self.window.tabs.setCurrentIndex(1)
        self.window.settings.cooldown.setText("1.8")
        self.window.tabs.setCurrentIndex(0)
        self.messages.advance()
        before = self.messages.path.read_bytes()
        self.wait_for_release()
        self.assertEqual(page.list_widget.count(), 0)
        self.assertFalse(page._items_by_key)
        self.assertFalse(page.list_widget.itemDelegate()._sizes)
        self.assertFalse(page.search_timer.isActive())
        self.assertFalse(page.list_widget.layout_timer.isActive())
        self.assertFalse(self.window.background_timer.isActive())
        self.assertEqual(self.messages.position, 1)
        self.messages.advance()  # The sender still owns the full message library.
        self.window.reveal()
        self.app.processEvents()
        self.assertEqual(page.list_widget.count(), 300)
        self.assertEqual(page.search.text(), "01")
        self.assertEqual(page.selected_rows(), [150, 151])
        self.assertEqual(page.list_widget.currentRow(), 150)
        self.assertEqual(page.list_widget.verticalScrollBar().value(), scroll)
        self.assertEqual(self.window.settings.cooldown.text(), "1.8")
        self.assertEqual(page.next_label.text(), "消息 0002")
        self.assertEqual(self.messages.path.read_bytes(), before)

    def test_quick_reopen_cancels_release_and_repeated_cycles_restore_current_library(self):
        page = self.window.management
        original = page.list_widget.item(0)
        self.window.background_timer.setInterval(40)
        self.window.close()
        self.window.reveal()
        QTest.qWait(100)
        self.assertIs(page.list_widget.item(0), original)
        for attempt in range(3):
            self.wait_for_release()
            self.messages.edit_message(0, f"修改 {attempt}")
            self.window.reload_messages()
            page.filter_messages()  # Pending hidden callbacks must be harmless.
            self.assertEqual(page.list_widget.count(), 0)
            self.window.reveal()
            self.assertEqual(page.list_widget.item(0).data(Qt.ItemDataRole.UserRole), f"修改 {attempt}")
            self.assertEqual(page.list_widget.count(), 300)

    def test_import_and_shutdown_defer_or_cancel_release(self):
        page = self.window.management
        page.import_worker = Mock()
        self.wait_for_release()
        self.assertEqual(page.list_widget.count(), 300)
        self.assertTrue(self.window.background_timer.isActive())
        page.import_worker = None
        QTest.qWait(100)
        self.assertEqual(page.list_widget.count(), 0)
        self.window.reveal()
        self.window.close()
        self.window.begin_shutdown()
        QTest.qWait(100)
        self.assertEqual(page.list_widget.count(), 300)
        self.assertFalse(self.window.background_timer.isActive())

    def test_update_or_modal_dialog_keeps_list_until_it_is_safe_to_release(self):
        self.window.updater.busy = True
        self.wait_for_release()
        self.assertEqual(self.window.management.list_widget.count(), 300)
        self.window.updater.busy = False
        dialog = QDialog(self.window)
        dialog.setModal(True)
        dialog.show()
        try:
            QTest.qWait(100)
            self.assertEqual(self.window.management.list_widget.count(), 300)
        finally:
            dialog.hide()
            dialog.deleteLater()
        QTest.qWait(100)
        self.assertEqual(self.window.management.list_widget.count(), 0)

    def test_minimize_releases_and_restore_rebuilds_list(self):
        self.window.background_timer.setInterval(10)
        self.window.showMinimized()
        QTest.qWait(100)
        self.assertEqual(self.window.management.list_widget.count(), 0)
        self.sender.busy = True
        self.window.refresh_status()
        self.assertFalse(self.window.timer.isActive())
        self.sender.busy = False
        self.window.showNormal()
        self.app.processEvents()
        self.assertEqual(self.window.management.list_widget.count(), 300)

    def test_empty_selection_survives_release(self):
        widget = self.window.management.list_widget
        widget.setCurrentRow(-1)
        widget.clearSelection()
        self.wait_for_release()
        self.window.reveal()
        self.assertEqual(widget.currentRow(), -1)
        self.assertEqual(widget.selectedItems(), [])


if __name__ == "__main__":
    unittest.main()

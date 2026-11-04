"""UI behavior regressions; no real keyboard delivery or user data access."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from valorant_toxic_tamer.config_manager import ConfigManager
from valorant_toxic_tamer.message_manager import MessageManager
from valorant_toxic_tamer.sender import Sender
from valorant_toxic_tamer.ui import MainWindow


class DesignUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        root = Path(self.temp.name)
        self.messages = MessageManager(root / "messages.json")
        self.messages.replace(["第一条", "第二条", "第三条"])
        self.config = ConfigManager(root / "config.json")
        self.sender = Sender(self.messages, Mock())
        self.window = MainWindow(self.messages, self.config, self.sender, self.config.save)
        self.window.error = Mock()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.sender.stop()
        self.window.updater.shutdown()
        self.window.timer.stop()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_edit_selection_does_not_change_next_message(self):
        self.window.list_widget.setCurrentRow(2)
        self.assertEqual(self.messages.index, 0)
        self.assertEqual(self.window.next_index, 0)
        self.assertEqual(self.window.next_label.text(), "第一条")
        self.messages.advance()
        self.window.refresh_status()
        self.assertEqual(self.window.list_widget.currentRow(), 2)
        self.assertEqual(self.window.next_index, 1)
        self.assertEqual(self.window.next_label.text(), "第二条")

    def test_busy_and_empty_states_disable_only_applicable_actions(self):
        self.window.list_widget.setCurrentRow(0)
        self.assertFalse(self.window.up_button.isEnabled())
        self.assertTrue(self.window.down_button.isEnabled())
        self.sender.busy = True
        self.window.refresh_status()
        self.assertTrue(all(not b.isEnabled() for b in self.window.edit_buttons))
        self.assertFalse(self.window.save_button.isEnabled())
        self.sender.busy = False
        self.messages.replace([])
        self.window.reload_messages()
        self.assertEqual(self.window.message_stack.currentIndex(), 1)
        self.assertTrue(self.window.add_button.isEnabled())
        self.assertTrue(self.window.import_button.isEnabled())
        self.assertFalse(self.window.edit_button.isEnabled())
        self.assertFalse(self.window.export_button.isEnabled())

    def test_dropdown_popup_retains_keyboard_selection(self):
        self.window.tabs.setCurrentIndex(1)
        box = self.window.team_key
        box.setFocus()
        box.showPopup()
        self.assertTrue(box.opened)
        QTest.keyClick(box.view(), Qt.Key.Key_Down)
        QTest.keyClick(box.view(), Qt.Key.Key_Return)
        self.assertEqual(box.currentText(), "F9")
        self.assertFalse(box.opened)
        self.assertIn("未保存", self.window.settings_hint.text())
        self.window.load_settings()
        self.assertEqual(box.currentText(), "F8")
        self.assertNotIn("未保存", self.window.settings_hint.text())

    def complete_dialog(self, text=None, accept=True):
        def finish():
            dialog = self.app.activeModalWidget()
            if text is not None:
                dialog.input.setText(text)
            dialog.accept() if accept else dialog.reject()
        QTimer.singleShot(0, finish)

    def test_add_edit_and_cancel_preserve_message_persistence_contract(self):
        self.messages.advance()
        self.complete_dialog("新增消息")
        self.window.add_message()
        self.assertEqual(self.messages.messages[-1], "新增消息")
        self.assertEqual(self.messages.index, 0)
        self.window.list_widget.setCurrentRow(1)
        self.complete_dialog("修改消息")
        self.window.edit_message()
        self.assertEqual(self.messages.messages[1], "修改消息")
        self.complete_dialog("不应保存", accept=False)
        self.window.add_message()
        self.assertNotIn("不应保存", self.messages.messages)
        self.assertEqual(MessageManager(self.messages.path).messages, self.messages.messages)

    def test_blank_message_is_rejected_without_changing_saved_list(self):
        before = self.messages.path.read_bytes()
        self.complete_dialog("   ")
        self.window.add_message()
        self.window.error.assert_called_once()
        self.assertEqual(self.messages.path.read_bytes(), before)

    def test_minimum_size_keeps_primary_controls_inside_workspaces(self):
        self.window.resize(860, 680)
        self.messages.replace(["很长的消息" * 100])
        self.window.reload_messages()
        self.app.processEvents()
        for button in self.window.edit_buttons:
            self.assertTrue(button.parentWidget().rect().contains(button.geometry()))
        self.window.tabs.setCurrentIndex(1)
        self.app.processEvents()
        for widget in (self.window.team_key, self.window.all_key, self.window.cooldown,
                       self.window.save_button, self.window.update_button):
            self.assertTrue(widget.parentWidget().rect().contains(widget.geometry()))
        self.assertEqual(self.window.list_widget.horizontalScrollBar().maximum(), 0)


if __name__ == "__main__":
    unittest.main()

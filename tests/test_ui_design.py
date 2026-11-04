"""UI behavior regressions; no real keyboard delivery or user data access."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QScrollArea, QStyleOptionViewItem

from valorant_toxic_tamer.config_manager import ConfigManager
from valorant_toxic_tamer.message_manager import MessageManager
from valorant_toxic_tamer.sender import Sender
from valorant_toxic_tamer.ui import MainWindow
from valorant_toxic_tamer.ui_theme import MessageDialog, style_message_box


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
        self.window.tabs.setCurrentIndex(1)
        self.window.tabs.setCurrentIndex(0)
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
        self.assertFalse(self.window.clear_button.isEnabled())
        self.assertFalse(self.window.export_button.isEnabled())

    def test_clear_list_confirms_count_and_persists_empty_state(self):
        self.messages.advance()
        self.window.list_widget.setCurrentRow(-1)
        self.assertTrue(self.window.clear_button.isEnabled())
        observed = {}

        def confirm():
            dialog = self.app.activeModalWidget()
            observed["text"] = dialog.text()
            observed["default"] = dialog.standardButton(dialog.defaultButton())
            dialog.button(QMessageBox.StandardButton.Yes).click()

        QTimer.singleShot(0, confirm)
        QTest.mouseClick(self.window.clear_button, Qt.MouseButton.LeftButton)
        self.assertIn("全部 3 条消息", observed["text"])
        self.assertEqual(observed["default"], QMessageBox.StandardButton.No)
        self.assertEqual(self.messages.messages, [])
        self.assertEqual(MessageManager(self.messages.path).messages, [])
        self.assertEqual(self.messages.index, 0)
        self.assertEqual(self.window.list_widget.count(), 0)
        self.assertEqual(self.window.message_stack.currentIndex(), 1)
        self.assertEqual(self.window.count_label.text(), "0 条")
        self.assertEqual(self.window.next_label.text(), "暂无消息")
        self.assertIn("0 / 0", self.window.state_label.text())
        self.assertFalse(self.window.clear_button.isEnabled())
        self.assertFalse(self.window.delete_button.isEnabled())
        self.assertFalse(self.window.export_button.isEnabled())

    def test_clear_list_cancel_enter_escape_and_close_preserve_messages(self):
        self.messages.advance()
        before = self.messages.path.read_bytes()
        for action in ("cancel", "enter", "escape", "close"):
            with self.subTest(action=action):
                def cancel():
                    dialog = self.app.activeModalWidget()
                    if action == "cancel":
                        dialog.button(QMessageBox.StandardButton.No).click()
                    elif action == "close":
                        dialog.close()
                    else:
                        QTest.keyClick(dialog, Qt.Key.Key_Return if action == "enter" else Qt.Key.Key_Escape)
                QTimer.singleShot(0, cancel)
                self.window.clear_messages()
                self.assertEqual(self.messages.path.read_bytes(), before)
                self.assertEqual(self.messages.messages, ["第一条", "第二条", "第三条"])
                self.assertEqual(self.messages.index, 1)
                self.assertEqual(self.window.list_widget.count(), 3)

    def test_clear_list_save_failure_keeps_messages_and_progress(self):
        self.messages.advance()
        before = self.messages.path.read_bytes()
        QTimer.singleShot(0, lambda: self.app.activeModalWidget().button(QMessageBox.StandardButton.Yes).click())
        with patch("valorant_toxic_tamer.config_manager.os.replace", side_effect=OSError("disk full")):
            self.window.clear_messages()
        self.window.error.assert_called_once()
        self.assertEqual(self.messages.path.read_bytes(), before)
        self.assertEqual(self.messages.messages, ["第一条", "第二条", "第三条"])
        self.assertEqual(self.messages.index, 1)
        self.assertEqual(self.window.list_widget.count(), 3)

    def test_clear_list_rechecks_sending_state_after_confirmation(self):
        before = self.messages.path.read_bytes()

        def confirm_while_busy():
            self.sender.busy = True
            self.app.activeModalWidget().button(QMessageBox.StandardButton.Yes).click()

        QTimer.singleShot(0, confirm_while_busy)
        try:
            self.window.clear_messages()
        finally:
            self.sender.busy = False
        self.window.error.assert_called_once()
        self.assertEqual(self.messages.path.read_bytes(), before)
        self.assertEqual(self.messages.messages, ["第一条", "第二条", "第三条"])

    def test_clear_empty_list_does_not_open_confirmation_or_save(self):
        self.messages.replace([])
        self.window.reload_messages()
        with patch("valorant_toxic_tamer.ui.QMessageBox") as dialog, patch.object(self.messages, "replace") as replace:
            self.window.clear_messages()
        dialog.assert_not_called()
        replace.assert_not_called()

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
        self.window.resize(840, 638)
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

    def test_font_size_save_applies_to_list_dialogs_and_restart(self):
        self.window.tabs.setCurrentIndex(1)
        self.messages.replace(["消息换行测试" * 25])
        self.window.reload_messages()
        self.app.processEvents()
        old_height = self.window.list_widget.sizeHintForRow(0)
        self.window.font_size.setFocus()
        QTest.keyClick(self.window.font_size, Qt.Key.Key_End)
        self.assertEqual(self.window.font_size.currentData(), 16)
        self.assertIn("未保存", self.window.settings_hint.text())
        self.assertEqual(self.window.list_widget.font().pixelSize(), 13)
        QTest.mouseClick(self.window.save_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(self.config.value["font_size"], 16)
        self.assertEqual(ConfigManager(self.config.path).value["font_size"], 16)
        self.assertEqual(self.window.list_widget.font().pixelSize(), 16)
        self.assertGreater(self.window.list_widget.sizeHintForRow(0), old_height)
        self.assertEqual(self.window.next_label.font().pixelSize(), 24)
        for dialog in (MessageDialog(self.window, "添加消息"), QMessageBox(self.window)):
            try:
                if isinstance(dialog, QMessageBox):
                    style_message_box(dialog)
                dialog.ensurePolished()
                self.assertEqual(dialog.font().pixelSize(), 16)
            finally:
                dialog.deleteLater()
        restarted = MainWindow(self.messages, ConfigManager(self.config.path), self.sender, self.config.save)
        try:
            restarted.tabs.setCurrentIndex(1)
            restarted.ensurePolished()
            self.assertEqual(restarted.font_size.currentData(), 16)
            self.assertEqual(restarted.list_widget.font().pixelSize(), 16)
        finally:
            restarted.timer.stop()
            restarted.updater.shutdown()
            restarted.deleteLater()

    def test_wheel_over_font_size_scrolls_settings_without_changing_selection(self):
        self.window.resize(840, 638)
        self.window.tabs.setCurrentIndex(1)
        box = self.window.font_size
        scroll = self.window.tabs.currentWidget().findChild(QScrollArea)
        before = self.config.path.read_bytes()
        self.app.processEvents()
        for focused in (False, True):
            for delta in (-120, 120):
                with self.subTest(focused=focused, delta=delta):
                    (box if focused else self.window.save_button).setFocus()
                    scroll.ensureWidgetVisible(box)
                    self.app.processEvents()
                    position = box.mapTo(self.window, box.rect().center())
                    old_scroll = scroll.verticalScrollBar().value()
                    QTest.wheelEvent(self.window.windowHandle(), position, QPoint(0, delta))
                    self.app.processEvents()
                    self.assertEqual(box.currentData(), 13)
                    self.assertNotIn("未保存", self.window.settings_hint.text())
                    self.assertEqual(self.config.path.read_bytes(), before)
                    if delta < 0:
                        self.assertGreater(scroll.verticalScrollBar().value(), old_scroll)
                    else:
                        self.assertLess(scroll.verticalScrollBar().value(), old_scroll)

    def test_font_size_popup_still_accepts_mouse_selection(self):
        self.window.tabs.setCurrentIndex(1)
        box = self.window.font_size
        scroll = self.window.tabs.currentWidget().findChild(QScrollArea)
        scroll.ensureWidgetVisible(box)
        self.app.processEvents()
        QTest.mouseClick(box, Qt.MouseButton.LeftButton)
        self.assertTrue(box.opened)
        # Let Qt's guard against the popup-opening click expire before selection.
        QTest.qWait(QApplication.doubleClickInterval() + 10)
        target = box.model().index(box.findData(14), 0)
        box.view().scrollTo(target)
        self.app.processEvents()
        QTest.mouseMove(box.view().viewport(), box.view().visualRect(target).center())
        QTest.mouseClick(box.view().viewport(), Qt.MouseButton.LeftButton,
                         pos=box.view().visualRect(target).center())
        self.assertFalse(box.opened)
        self.assertEqual(box.currentData(), 14)
        self.assertIn("未保存", self.window.settings_hint.text())

    def test_failed_font_save_keeps_previous_font_and_config(self):
        self.window.font_size.setCurrentIndex(self.window.font_size.findData(16))
        before = self.config.path.read_bytes()
        with patch("valorant_toxic_tamer.config_manager.os.replace", side_effect=OSError("disk full")):
            self.window.apply_settings()
        self.window.error.assert_called_once()
        self.assertEqual(self.config.path.read_bytes(), before)
        self.assertEqual(self.window.font_size.currentData(), 13)
        self.assertEqual(self.window.list_widget.font().pixelSize(), 13)

    def test_largest_font_keeps_controls_readable_at_minimum_window_size(self):
        self.window.resize(840, 638)
        self.window.font_size.setCurrentIndex(self.window.font_size.findData(16))
        self.window.apply_settings()
        self.app.processEvents()
        for hint in (self.window.team_hint, self.window.all_hint):
            self.assertGreaterEqual(hint.contentsRect().width(),
                                    hint.fontMetrics().horizontalAdvance(hint.text()))
        self.assertGreaterEqual(self.window.next_label.height(),
                                self.window.next_label.fontMetrics().lineSpacing() * 3)
        for button in self.window.edit_buttons:
            self.assertTrue(button.parentWidget().rect().contains(button.geometry()))
        self.window.tabs.setCurrentIndex(1)
        self.app.processEvents()
        # The settings page scrolls vertically; save remains outside the scroll area.
        scroll = self.window.tabs.currentWidget().findChild(QScrollArea)
        scroll.ensureWidgetVisible(self.window.font_size)
        self.app.processEvents()
        top_left = self.window.font_size.mapTo(scroll.viewport(), self.window.font_size.rect().topLeft())
        self.assertTrue(scroll.viewport().rect().contains(top_left))
        self.assertTrue(self.window.save_button.isVisible())
        menu = QMenu(self.window)
        menu.addAction("设置")
        menu.ensurePolished()
        self.assertEqual(menu.font().pixelSize(), 16)
        menu.deleteLater()

    def test_update_channel_and_button_remain_reachable_at_largest_font(self):
        self.window.resize(840, 638)
        self.window.tabs.setCurrentIndex(1)
        self.window.font_size.setCurrentIndex(self.window.font_size.findData(16))
        self.window.apply_settings()
        self.window.update_channel.setCurrentIndex(self.window.update_channel.findData("beta"))
        self.app.processEvents()
        scroll = self.window.tabs.widget(1).findChild(QScrollArea)
        for control in (self.window.update_channel, self.window.update_button):
            scroll.ensureWidgetVisible(control)
            self.app.processEvents()
            top_left = control.mapTo(scroll.viewport(), control.rect().topLeft())
            bottom_right = control.mapTo(scroll.viewport(), control.rect().bottomRight())
            self.assertTrue(scroll.viewport().rect().contains(top_left))
            self.assertTrue(scroll.viewport().rect().contains(bottom_right))
        self.assertGreaterEqual(self.window.update_button.width(), self.window.update_button.sizeHint().width())

    def test_long_preview_can_scroll_to_end_and_resets_for_next_message(self):
        text = "长消息：" + "注意配合，等待队友一起行动。" * 30 + "末尾检查"
        self.messages.replace([text, "下一条短消息"])
        self.window.reload_messages()
        self.window.resize(840, 638)
        self.window.font_size.setCurrentIndex(self.window.font_size.findData(16))
        self.window.apply_settings()
        self.app.processEvents()
        preview = self.window.next_label
        self.assertEqual(preview.text(), text)
        self.assertGreaterEqual(preview.height(), preview.heightForWidth(preview.width()))
        scroll = self.window.tabs.widget(0).findChild(QScrollArea)
        end = preview.mapTo(scroll.widget(), preview.rect().bottomLeft())
        scroll.ensureVisible(end.x(), end.y(), 8, 8)
        self.app.processEvents()
        self.assertGreater(scroll.verticalScrollBar().value(), 0)
        self.assertTrue(scroll.viewport().rect().contains(
            preview.mapTo(scroll.viewport(), preview.rect().bottomLeft())))
        self.messages.advance()
        self.window.refresh_status()
        self.app.processEvents()
        self.assertEqual(preview.text(), "下一条短消息")
        self.assertEqual(scroll.verticalScrollBar().value(), 0)
        self.assertLess(preview.height(), scroll.viewport().height())

    def test_four_digit_progress_wraps_instead_of_clipping_at_largest_font(self):
        self.messages.replace(["测试消息"] * 1000)
        self.messages.index = 999
        self.window.reload_messages(999)
        self.window.resize(840, 638)
        self.window.font_size.setCurrentIndex(self.window.font_size.findData(16))
        self.window.apply_settings()
        self.app.processEvents()
        progress = self.window.progress_label
        self.assertIn("1000", progress.text())
        self.assertTrue(progress.sizeHint().width() <= progress.width() or progress.wordWrap())
        self.assertGreaterEqual(progress.height(), progress.heightForWidth(progress.width()))

        delegate = self.window.list_widget.itemDelegate()
        option = QStyleOptionViewItem()
        index = self.window.list_widget.model().index(999, 0)
        delegate.initStyleOption(option, index)
        option.rect = QRect(0, 0, self.window.list_widget.viewport().width(), 80)
        painter = Mock()
        delegate.paint(painter, option, index)
        number_rect = next(call.args[0] for call in painter.drawText.call_args_list
                           if call.args[-1] == "1000")
        text_rect = next(call.args[0] for call in painter.drawText.call_args_list
                         if call.args[-1] == "测试消息")
        self.assertGreaterEqual(number_rect.width(),
                                option.fontMetrics.horizontalAdvance("1000"))
        self.assertGreater(text_rect.left(), number_rect.right())


if __name__ == "__main__":
    unittest.main()

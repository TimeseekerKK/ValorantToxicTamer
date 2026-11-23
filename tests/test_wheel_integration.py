"""Category wheel configuration and normal app integration without real keyboard input."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from test_core import FakeAPI
from valorant_toxic_tamer.app import Application
from valorant_toxic_tamer.category_wheel import MOUSE_LEFT_DOWN, MOUSE_RIGHT_DOWN, WheelDraft
from valorant_toxic_tamer.ui_settings import WheelSettingsDialog
from valorant_toxic_tamer.wheel_settings import WheelSettings


class WheelIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.api = FakeAPI()
        self.api.kernel = Mock()
        self.api.user = Mock()
        self.api.user.RegisterHotKey.return_value = 1
        self.api.user.RegisterRawInputDevices.return_value = 1
        with patch("valorant_toxic_tamer.app.WindowsAPI", return_value=self.api), \
                patch("valorant_toxic_tamer.app.Tray"):
            self.controller = Application(self.app, self.root)
        self.addCleanup(self.cleanup_app)
        self.attack, self.callout, self.cheer = (
            self.controller.messages.create_category(name) for name in ("战术", "报点", "鼓励"))
        for cid, text in ((self.attack, "A"), (self.callout, "B"), (self.cheer, "C")):
            self.controller.messages.append([text + "1", text + "2"], cid)

    def cleanup_app(self):
        self.app.aboutToQuit.disconnect(self.controller.cleanup)
        self.controller.cleanup()
        if self.controller.window is not None:
            self.controller.window.deleteLater()
        self.app.processEvents()

    def test_saving_presets_and_clearing_runtime_selection_through_normal_window(self):
        ctl = self.controller
        self.assertIsNone(ctl.wheel)
        self.assertFalse(ctl.wheel_settings.path.exists())
        original = ctl.config.path.read_bytes()
        ctl.reveal(1)
        dialog = WheelSettingsDialog(ctl.window)
        items = {dialog.options.item(i).data(Qt.ItemDataRole.UserRole): dialog.options.item(i)
                 for i in range(dialog.options.count())}
        dialog.enabled.setChecked(True)
        for cid in (self.cheer, self.attack):
            items[cid].setCheckState(Qt.CheckState.Checked)
        dialog.save()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(ctl.wheel_settings.categories, (self.cheer, self.attack))
        self.assertEqual(ctl.config.path.read_bytes(), original)
        self.assertEqual(WheelSettings(ctl.wheel_settings.path).categories, (self.cheer, self.attack))

        ctl._select_wheel_categories((self.cheer, self.attack))
        page = ctl.window.management
        self.assertEqual(page.send_mode.full_text, "交替 · 鼓励 → 战术")
        self.assertEqual(page.next_label.text(), "C1")
        self.assertFalse(page.restore_cycle_button.isHidden())
        page.restore_cycle()
        self.assertEqual(ctl.messages.wheel_categories, ())
        self.assertEqual(page.next_label.text(), "A1")

    def test_tray_start_and_runtime_mouse_selection_use_the_existing_sender(self):
        ctl = self.controller
        self.assertIsNone(ctl.window)
        ctl.save_wheel_settings(True, (self.attack, self.callout, self.cheer))
        wheel = ctl.wheel
        wheel.center_on_target = lambda: True
        wheel.key(0x12, 0, 56)
        wheel.pressed_at -= 2.1
        wheel.poll()
        self.assertTrue(wheel.visible)
        self.assertFalse(ctl.trigger("team"))
        wheel.mouse(0, -60, MOUSE_LEFT_DOWN)
        wheel.mouse(60, 60, MOUSE_LEFT_DOWN)
        wheel.mouse(0, 0, MOUSE_RIGHT_DOWN)
        wheel.mouse(-60, 60, MOUSE_LEFT_DOWN)
        wheel.key(0x12, 1, 56)
        self.assertEqual(ctl.messages.wheel_categories, (self.attack, self.cheer))

        ctl.sender.wait = lambda seconds: None
        now = [10]
        ctl.sender.clock = lambda: now[0]
        for channel, expected in (("team", "A1"), ("all", "C1"), ("team", "A2")):
            self.api.events.clear()
            self.assertTrue(ctl.trigger(channel))
            ctl.sender.thread.join(2)
            self.assertFalse(ctl.sender.thread.is_alive())
            self.assertEqual("".join(char for char in self.api.events if isinstance(char, str)), expected)
            now[0] += 1
        ctl.save_wheel_settings(False, (self.attack,))
        self.assertIsNone(ctl.wheel)
        self.assertEqual(ctl.messages.wheel_categories, ())
        self.assertFalse(wheel.input.registered)

    def test_invalid_settings_leave_other_features_available(self):
        path = self.root / "category-wheel.json"
        path.write_bytes(b"bad")
        settings = WheelSettings(path)
        self.assertFalse(settings.enabled)
        self.assertTrue(settings.error)
        self.assertEqual(path.read_bytes(), b"bad")

    def test_enabled_presets_return_after_restart_without_reusing_runtime_selection(self):
        self.controller.save_wheel_settings(True, (self.cheer, self.attack))
        self.controller.sender.select_wheel_categories((self.cheer,))
        self.cleanup_app()
        with patch("valorant_toxic_tamer.app.WindowsAPI", return_value=self.api), \
                patch("valorant_toxic_tamer.app.Tray"):
            self.controller = Application(self.app, self.root)
        self.assertIsNone(self.controller.window)
        self.assertIsNotNone(self.controller.wheel)
        self.assertEqual(self.controller.wheel_settings.categories, (self.cheer, self.attack))
        self.assertEqual(self.controller.messages.wheel_categories, ())
        self.assertEqual(self.controller.messages.current, "A1")

    def test_failed_preset_save_releases_the_new_input_registration(self):
        ctl = self.controller
        with patch("valorant_toxic_tamer.wheel_settings.atomic_json", side_effect=OSError("write failed")):
            with self.assertRaises(OSError):
                ctl.save_wheel_settings(True, (self.attack,))
        self.assertIsNone(ctl.wheel)
        self.assertFalse(ctl.wheel_settings.enabled)
        self.assertFalse(ctl.wheel_settings.path.exists())
        self.assertEqual(self.api.user.RegisterRawInputDevices.call_count, 2)

    def test_wheel_rendering_options_skip_empty_categories_on_confirmation(self):
        draft = WheelDraft(((self.attack, "战术", True), (self.callout, "报点", False)),
                           (), {})
        draft.hover = 1
        draft.click(MOUSE_LEFT_DOWN)
        self.assertIsNone(draft.selection())
        draft.hover = 2
        self.assertEqual(draft.selection(), ())

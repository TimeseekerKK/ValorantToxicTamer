"""Settings transactions touch only changed fields and roll back applied effects."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from valorant_toxic_tamer.app import Application
from valorant_toxic_tamer.config_manager import ConfigManager


class SettingsChangesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.config = ConfigManager(Path(self.temp.name) / "config.json")
        self.controller = Mock(config=self.config, window=None)
        self.controller.sender.cooldown = self.config.value["cooldown"]
        self.controller.hotkeys.configure.return_value = True

    def test_no_changes_skip_persistence_and_all_side_effects(self):
        with patch.object(self.config, "save") as save, \
                patch("valorant_toxic_tamer.app.set_autostart") as registry:
            Application.save_settings(self.controller, self.config.value.copy())
        save.assert_not_called()
        registry.assert_not_called()
        self.controller.hotkeys.configure.assert_not_called()
        self.controller.tray.set_font_size.assert_not_called()

    def test_independent_fields_do_not_reregister_hotkeys(self):
        for key, value in (("font_size", 16), ("cooldown", 0.8), ("start_hidden", False),
                           ("autostart", True), ("category_mode", "alternating")):
            with self.subTest(key=key), patch("valorant_toxic_tamer.app.set_autostart") as registry:
                self.controller.tray.set_font_size.reset_mock()
                Application.save_settings(self.controller, {**self.config.value, key: value})
                self.controller.hotkeys.configure.assert_not_called()
                self.assertEqual(ConfigManager(self.config.path).value[key], value)
                self.assertEqual(registry.call_count, int(key == "autostart"))
                self.assertEqual(self.controller.tray.set_font_size.call_count, int(key == "font_size"))
                if key == "cooldown":
                    self.assertEqual(self.controller.sender.cooldown, value)
                if key == "category_mode":
                    self.controller.messages.set_mode.assert_called_once_with(value)

    def test_failed_autostart_save_rolls_back_only_registry(self):
        previous = self.config.value.copy()
        with patch.object(self.config, "save", side_effect=OSError("disk full")), \
                patch("valorant_toxic_tamer.app.set_autostart") as registry:
            with self.assertRaisesRegex(OSError, "disk full"):
                Application.save_settings(self.controller, {**previous, "autostart": True})
        self.assertEqual([call.args for call in registry.call_args_list], [(True,), (False,)])
        self.controller.hotkeys.configure.assert_not_called()
        self.assertEqual(self.config.value, previous)

    def test_failed_save_restores_changed_hotkeys_and_preserves_runtime(self):
        previous = self.config.value.copy()
        value = {**previous, "team_hotkey": "F7", "font_size": 16, "cooldown": 0.8,
                 "category_mode": "alternating"}
        with patch.object(self.config, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                Application.save_settings(self.controller, value)
        self.assertEqual([call.args[0] for call in self.controller.hotkeys.configure.call_args_list],
                         [value, previous])
        self.controller.tray.set_font_size.assert_not_called()
        self.controller.messages.set_mode.assert_not_called()
        self.assertEqual(self.controller.sender.cooldown, previous["cooldown"])

"""A broken optional preference must not prevent core application usage."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from valorant_toxic_tamer.config_manager import ConfigManager
from valorant_toxic_tamer.message_manager import MessageManager
from valorant_toxic_tamer.sender import Sender
from valorant_toxic_tamer.ui import MainWindow


class UpdateRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.path = self.root / "update_settings.json"
        self.path.write_bytes(b'{ broken')
        self.config = ConfigManager(self.root / "config.json")
        self.messages = MessageManager(self.root / "messages.json")
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

    def test_broken_preference_preserved_while_messages_remain_editable(self):
        self.assertEqual(self.window.updater.channel, "stable")
        self.assertIsNotNone(self.window.updater.preferences_error)
        self.window.change(lambda: self.messages.replace(["仍可使用"]))
        self.assertEqual(self.messages.messages, ["仍可使用"])
        self.assertEqual(self.path.read_bytes(), b'{ broken')
        self.window.tabs.setCurrentIndex(1)
        self.assertFalse(self.window.repair_update_button.isHidden())

    def test_repair_backs_up_exact_bytes_and_survives_restart(self):
        self.window.tabs.setCurrentIndex(1)
        self.window.repair_update_button.click()
        backups = list(self.root.glob("update_settings.invalid-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'{ broken')
        self.assertEqual(json.loads(self.path.read_text()), {"channel": "stable"})
        self.assertIsNone(self.window.updater.preferences_error)
        self.assertTrue(self.window.repair_update_button.isHidden())
        restarted = MainWindow(self.messages, self.config, self.sender, self.config.save)
        self.assertIsNone(restarted.updater.preferences_error)
        restarted.shutdown()
        restarted.deleteLater()

    def test_changing_channel_also_preserves_damaged_original(self):
        self.window.tabs.setCurrentIndex(1)
        self.window.update_channel.setCurrentIndex(self.window.update_channel.findData("beta"))
        self.assertEqual(self.window.updater.channel, "beta")
        self.assertEqual(next(self.root.glob("update_settings.invalid-*.json")).read_bytes(), b'{ broken')
        self.assertEqual(json.loads(self.path.read_text()), {"channel": "beta"})

    def test_backup_failure_does_not_overwrite_original_or_change_channel(self):
        self.window.tabs.setCurrentIndex(1)
        with patch("valorant_toxic_tamer.update_controller.shutil.copyfile", side_effect=OSError("denied")):
            self.window.update_channel.setCurrentIndex(self.window.update_channel.findData("beta"))
        self.assertEqual(self.path.read_bytes(), b'{ broken')
        self.assertEqual(self.window.updater.channel, "stable")
        self.assertEqual(self.window.update_channel.currentData(), "stable")
        self.window.error.assert_called_once()

    def test_failed_repair_keeps_original_and_recovery_available(self):
        self.window.tabs.setCurrentIndex(1)
        with patch("valorant_toxic_tamer.update_controller.atomic_json", side_effect=OSError("disk full")):
            self.window.repair_update_button.click()
        self.assertEqual(self.path.read_bytes(), b'{ broken')
        self.assertIsNotNone(self.window.updater.preferences_error)
        self.assertFalse(self.window.repair_update_button.isHidden())
        self.window.error.assert_called_once()

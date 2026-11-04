"""Offscreen update interactions; all network, replacement and exit are mocked."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from valorant_toxic_tamer.config_manager import ConfigManager
from valorant_toxic_tamer.message_manager import MessageManager
from valorant_toxic_tamer.sender import Sender
from valorant_toxic_tamer.ui import MainWindow
from valorant_toxic_tamer.updater import Release


class UpdateUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.directory = Path(self.temp.name).resolve()
        messages = MessageManager(self.directory / "messages.json")
        config = ConfigManager(self.directory / "config.json")
        self.sender = Sender(messages, Mock())
        self.window = MainWindow(messages, config, self.sender, Mock())
        self.window.error = Mock()
        self.updater = self.window.updater
        self.ready = Mock()
        self.updater.ready_to_install.connect(self.ready)
        self.release = Release("v1.1.0", "https://example.test/exe", 5, None)

    def tearDown(self):
        self.updater.shutdown()
        self.sender.stop()
        self.window.timer.stop()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def wait_until(self, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(condition())

    def test_no_declines_without_download_or_exit_and_exact_modal(self):
        def decline(dialog):
            self.assertEqual(dialog.text(), "发现新版本,是否更新")
            self.assertEqual(dialog.defaultButton().text(), "否")
            self.assertEqual(dialog.button(QMessageBox.StandardButton.Yes).text(), "是")
            return QMessageBox.StandardButton.No
        with patch("valorant_toxic_tamer.update_controller.latest_release", return_value=self.release), \
                patch.object(QMessageBox, "exec", decline), \
                patch("valorant_toxic_tamer.update_controller.download_release") as download:
            self.window.update_button.click()
            self.wait_until(lambda: not self.updater.busy)
            download.assert_not_called()
        self.ready.assert_not_called()
        self.assertTrue(self.window.update_button.isEnabled())

    def test_yes_downloads_then_hands_off_before_exit_signal(self):
        staged = self.directory / "staged.exe"
        staged.write_bytes(b"MZnew")
        target = self.directory / "installed.exe"
        with patch("valorant_toxic_tamer.update_controller.latest_release", return_value=self.release), \
                patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes), \
                patch("valorant_toxic_tamer.update_controller.installed_executable", return_value=target), \
                patch("valorant_toxic_tamer.update_controller.download_release", return_value=staged) as download, \
                patch("valorant_toxic_tamer.update_controller.launch_installer") as install:
            self.window.update_button.click()
            self.wait_until(lambda: self.ready.called)
            download.assert_called_once_with(self.release, target, self.updater.cancel)
            install.assert_called_once_with(staged, target)
        self.ready.assert_called_once()

    def test_latest_version_and_check_failure_restore_button(self):
        with patch("valorant_toxic_tamer.update_controller.latest_release", return_value=None), \
                patch.object(self.window, "information") as info:
            self.window.update_button.click()
            self.wait_until(lambda: not self.updater.busy)
            info.assert_called_once()
        with patch("valorant_toxic_tamer.update_controller.latest_release", side_effect=OSError("offline")):
            self.window.update_button.click()
            self.wait_until(lambda: not self.updater.busy)
            self.window.error.assert_called_once_with("offline")
        self.assertTrue(self.window.update_button.isEnabled())
        self.ready.assert_not_called()

    def test_download_or_handoff_failure_does_not_exit(self):
        for stage in ("download", "install"):
            staged = self.directory / "staged.exe"
            staged.write_bytes(b"MZnew")
            self.window.error.reset_mock()
            with patch("valorant_toxic_tamer.update_controller.latest_release", return_value=self.release), \
                    patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes), \
                    patch("valorant_toxic_tamer.update_controller.installed_executable", return_value=self.directory / "installed.exe"), \
                    patch("valorant_toxic_tamer.update_controller.download_release", side_effect=OSError("failed") if stage == "download" else None,
                          return_value=staged), \
                    patch("valorant_toxic_tamer.update_controller.launch_installer", side_effect=OSError("failed")) as install:
                self.window.update_button.click()
                self.wait_until(lambda: not self.updater.busy)
                self.window.error.assert_called_once_with("failed")
                if stage == "download":
                    install.assert_not_called()
                else:
                    self.assertFalse(staged.exists())
        self.ready.assert_not_called()

    def test_background_check_keeps_events_responsive_and_ignores_double_click(self):
        unblock = threading.Event()
        self.addCleanup(unblock.set)
        def lookup():
            unblock.wait(3)
            return None
        with patch("valorant_toxic_tamer.update_controller.latest_release", side_effect=lookup) as lookup_mock, \
                patch.object(self.window, "information"):
            self.window.update_button.click()
            QTest.qWait(50)
            self.assertFalse(self.window.update_button.isEnabled())
            self.updater.check()
            self.assertEqual(lookup_mock.call_count, 1)
            self.assertTrue(self.updater.busy)
            unblock.set()
            self.wait_until(lambda: not self.updater.busy)


if __name__ == "__main__":
    unittest.main()

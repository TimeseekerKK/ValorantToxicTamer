"""UAC handoff, command quoting and failure behavior without showing prompts."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from valorant_toxic_tamer import elevation


class ElevationTests(unittest.TestCase):
    def setUp(self):
        self.shell = Mock()
        self.shell.IsUserAnAdmin.return_value = 0
        self.shell.ShellExecuteW.return_value = 42
        self.library = patch.object(elevation.ctypes, "WinDLL", return_value=self.shell)
        self.library.start()
        self.addCleanup(self.library.stop)
        self.messages = patch.object(elevation.ctypes.windll.user32, "MessageBoxW")
        self.message = self.messages.start()
        self.addCleanup(self.messages.stop)

    def test_already_admin_does_not_relaunch(self):
        self.shell.IsUserAnAdmin.return_value = 1
        self.assertIsNone(elevation.ensure_administrator())
        self.shell.ShellExecuteW.assert_not_called()

    def test_source_relaunch_preserves_arguments(self):
        args = ["main.py", "含 空格", 'a"b', "C:\\trailing space\\"]
        with patch.object(sys, "argv", args), patch.object(sys, "frozen", False, create=True):
            self.assertEqual(elevation.ensure_administrator(), 0)
        self.shell.ShellExecuteW.assert_called_once_with(
            None, "runas", sys.executable,
            subprocess.list2cmdline([str(Path(elevation.__file__).resolve().parents[1] / "main.py"),
                                    *args[1:]]), os.getcwd(), 1)

    def test_frozen_relaunch_resets_bundle_environment_and_restores_parent(self):
        for previous in (None, "old"):
            with self.subTest(previous=previous), patch.dict(os.environ):
                if previous is None:
                    os.environ.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
                else:
                    os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = previous

                def execute(*args):
                    self.assertEqual(os.environ["PYINSTALLER_RESET_ENVIRONMENT"], "1")
                    self.assertEqual(args[3], '"argument with space"')
                    return 42

                self.shell.ShellExecuteW.side_effect = execute
                with patch.object(sys, "argv", ["app.exe", "argument with space"]), \
                        patch.object(sys, "frozen", True, create=True):
                    self.assertEqual(elevation.ensure_administrator(), 0)
                self.assertEqual(os.environ.get("PYINSTALLER_RESET_ENVIRONMENT"), previous)

    def test_cancel_or_failure_does_not_start_unelevated(self):
        for result in (None, 0, 5, 32):
            with self.subTest(result=result):
                self.shell.ShellExecuteW.return_value = result
                self.assertEqual(elevation.ensure_administrator(), 1)
        self.assertEqual(self.message.call_count, 4)

    def test_application_stops_before_qt_when_handoff_or_denied(self):
        from valorant_toxic_tamer import app
        for status in (0, 1):
            with patch.object(sys, "argv", ["main.py"]), \
                    patch.object(elevation, "ensure_administrator", return_value=status), \
                    patch.object(app, "QApplication") as qt:
                self.assertEqual(app.main(), status)
                qt.assert_not_called()

    def test_non_windows_does_not_request_uac(self):
        with patch.object(sys, "platform", "linux"):
            self.assertIsNone(elevation.ensure_administrator())
        self.shell.IsUserAnAdmin.assert_not_called()

    def test_startup_diagnostics_do_not_request_uac(self):
        from valorant_toxic_tamer import app, startup_check
        for option, function in (("--startup-check", "run"),
                                 ("--update-check-smoke", "run_update_check")):
            with self.subTest(option=option), \
                    patch.object(sys, "argv", ["app.exe", option, "report.json"]), \
                    patch.object(elevation, "ensure_administrator") as elevate, \
                    patch.object(app, "QApplication"), \
                    patch.object(startup_check, function, return_value=0):
                self.assertEqual(app.main(), 0)
                elevate.assert_not_called()

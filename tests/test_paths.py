"""Keep stored data and startup commands stable across source reorganization."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import winreg

from valorant_toxic_tamer.config_manager import data_directory, set_autostart


class PathTests(unittest.TestCase):
    def test_source_uses_existing_project_data(self):
        with patch("sys.frozen", False, create=True):
            self.assertEqual(data_directory(), Path(__file__).resolve().parents[1] / "data")

    def test_frozen_uses_data_beside_actual_executable(self):
        with patch("sys.frozen", True, create=True), \
                patch("sys.executable", "D:/Apps/中文 test/ValorantToxicTamer.exe"):
            self.assertEqual(data_directory(), Path(sys.executable).resolve().parent / "data")

    def test_source_autostart_points_to_root_launcher(self):
        executable = Path(sys.executable)
        windowless = executable.with_name("pythonw.exe")
        launcher = Path(__file__).resolve().parents[1] / "main.py"
        with patch("sys.frozen", False, create=True), \
                patch.object(winreg, "CreateKeyEx"), patch.object(winreg, "SetValueEx") as write:
            set_autostart(True)
        command = write.call_args.args[-1]
        self.assertEqual(command, subprocess.list2cmdline([
            str(windowless if windowless.exists() else executable), str(launcher),
        ]))
        self.assertTrue(launcher.is_file())

    def test_frozen_autostart_uses_only_executable(self):
        with patch("sys.frozen", True, create=True), \
                patch.object(winreg, "CreateKeyEx"), patch.object(winreg, "SetValueEx") as write:
            set_autostart(True)
        self.assertEqual(write.call_args.args[-1], subprocess.list2cmdline([str(Path(sys.executable))]))


if __name__ == "__main__":
    unittest.main()

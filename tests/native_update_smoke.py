"""Real replacement/forced-exit smoke test, using disposable fixture EXEs only.

Run explicitly: .venv\\Scripts\\python.exe tests/native_update_smoke.py
Never starts ValorantToxicTamer or sends keyboard input.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from updater import launch_installer


@unittest.skipUnless(sys.platform == "win32", "Windows updater integration")
class NativeUpdateSmoke(unittest.TestCase):
    def setUp(self):
        # Spaces, Chinese, apostrophes and shell metacharacters are path data.
        self.temp = tempfile.TemporaryDirectory(prefix="更新 test '&$-", dir=Path(__file__).parent)
        self.directory = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)
        self.compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        self.processes = []
        self.addCleanup(self.stop_fixtures)

    def stop_fixtures(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)

    def build_fixture(self, path, version, wait):
        source = path.with_suffix(".cs")
        source.write_text('''using System;
using System.IO;
using System.Threading;
class Fixture {
    static void Main() {
        string folder = AppDomain.CurrentDomain.BaseDirectory;
        File.WriteAllText(Path.Combine(folder, "VERSION.marker"), "VERSION");
        Thread.Sleep(WAIT);
    }
}'''.replace("VERSION", version).replace("WAIT", str(wait)), encoding="utf-8")
        subprocess.run([str(self.compiler), "/nologo", "/target:winexe", f"/out:{path}", str(source)],
                       check=True, capture_output=True, timeout=30)

    def wait_until(self, check):
        deadline = time.monotonic() + 30
        while not check() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(check())

    def test_force_exit_replace_restart_and_other_installation_survives(self):
        target = self.directory / "fixture.exe"
        staged = self.directory / "staged.exe"
        self.build_fixture(target, "old", 60000)
        self.build_fixture(staged, "new", 0)
        expected = hashlib.sha256(staged.read_bytes()).hexdigest()
        other_directory = self.directory / "other installation"
        other_directory.mkdir()
        decoy = other_directory / target.name
        shutil.copyfile(target, decoy)
        for exe in (target, decoy):
            self.processes.append(subprocess.Popen([str(exe)], creationflags=subprocess.CREATE_NO_WINDOW))
        self.wait_until(lambda: (self.directory / "old.marker").exists()
                        and (other_directory / "old.marker").exists())
        helper = self.directory / "helper"
        helper.mkdir()
        with patch("updater.tempfile.mkdtemp", return_value=str(helper)):
            installer = launch_installer(staged, target)
        self.processes.append(installer)
        self.wait_until(lambda: (self.directory / "new.marker").exists() or (helper / "error.txt").exists())
        if (helper / "error.txt").exists():
            self.fail((helper / "error.txt").read_text(encoding="utf-8-sig"))
        self.assertIsNotNone(self.processes[0].poll())
        self.assertIsNone(self.processes[1].poll())
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), expected)
        self.assertFalse(staged.exists())
        self.wait_until(lambda: not Path(str(staged) + ".bak").exists())
        installer.wait(timeout=10)

    def test_helper_rejects_checksum_before_terminating_or_replacing(self):
        target = self.directory / "fixture.exe"
        staged = self.directory / "staged.exe"
        target.write_bytes(b"original")
        staged.write_bytes(b"changed download")
        helper = self.directory / "helper"
        helper.mkdir()
        script = helper / "install.ps1"
        shutil.copyfile(Path(__file__).resolve().parents[1] / "update_install.ps1", script)
        manifest = helper / "update.json"
        manifest.write_text(json.dumps(dict(target=str(target), staged=str(staged), pid=os.getpid(),
                                            sha256="0" * 64)), encoding="utf-8-sig")
        powershell = Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-File", str(script), "-Manifest", str(manifest)], check=True, timeout=30,
                       creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True)
        self.assertEqual(target.read_bytes(), b"original")
        self.assertIn("checksum", (helper / "error.txt").read_text(encoding="utf-8-sig"))
        self.assertFalse((helper / "ready").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

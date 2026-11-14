"""Real installer lifecycle using an isolated AppId and disposable data only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import winreg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from valorant_toxic_tamer.app_version import VERSION

TEST_GUID = "213401C8-7215-423B-A44B-59BDEDB68F61"


class NativeInstallerSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="安装验证 test '&$ ", dir=ROOT / "artifacts")
        cls.root = Path(cls.temp.name).resolve()
        compiler = Path(os.environ.get("INNO_SETUP_COMPILER", ROOT / ".tools/InnoSetup6/ISCC.exe"))
        exe = ROOT / f"dist/ValorantToxicTamer-v{VERSION}.exe"
        result = subprocess.run([str(compiler), f"/DAppVersion={VERSION}", f"/DAppExe={exe}",
            f"/DAppGuid={TEST_GUID}", "/DAppTitle=ValorantToxicTamer 安装验证", "/DTestBuild=1",
            f"/O{cls.root}", str(ROOT / "installer/ValorantToxicTamer.iss")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.setup = cls.root / f"ValorantToxicTamer-Setup-v{VERSION}.exe"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_exe(self, exe, *arguments):
        result = subprocess.run([str(exe), *arguments], capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, f"exit={result.returncode}: {exe}")

    def install(self, directory):
        self.run_exe(self.setup, "/CURRENTUSER", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                     f"/DIR={directory}", f"/LOG={self.root / 'setup.log'}")

    def wait_until(self, predicate):
        deadline = time.monotonic() + 20
        while not predicate() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(predicate(), "Uninstaller child process did not finish")

    def test_install_upgrade_preserve_then_delete_with_junction(self):
        parent = self.root / "中文 Apps"
        install = parent / "ValorantToxicTamer"
        self.install(parent)
        self.assertTrue((install / "ValorantToxicTamer.exe").is_file())
        self.assertTrue((install / "licenses/InnoSetupChineseSimplified.txt").is_file())
        self.assertFalse((install / "ValorantToxicTamer").exists())
        data = install / "data"
        data.mkdir()
        payload = b"personal-data-exact-bytes"
        (data / "messages.json").write_bytes(payload)
        (install / "manual.txt").write_text("user file", encoding="utf-8")
        self.install(install)
        self.assertEqual((data / "messages.json").read_bytes(), payload)
        self.assertFalse((install / "ValorantToxicTamer").exists())
        self.run_exe(install / "unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/KEEPDATA=1")
        self.wait_until(lambda: not list(install.glob('unins*.exe')))
        self.assertFalse((install / "ValorantToxicTamer.exe").exists())
        self.assertEqual((data / "messages.json").read_bytes(), payload)
        self.install(install)
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("must survive", encoding="utf-8")
        # cmd's mklink is used only to CREATE a junction in the disposable fixture.
        subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(install / "external-link"), str(outside)],
                       check=True, capture_output=True)
        self.run_exe(install / "unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/KEEPDATA=0",
                     f"/LOG={ROOT / 'artifacts/installer-uninstall.log'}")
        self.wait_until(lambda: not install.exists())
        self.assertFalse(install.exists(), str(list(install.rglob('*'))) if install.exists() else '')
        self.assertEqual((outside / "keep.txt").read_text(encoding="utf-8"), "must survive")
        with self.assertRaises(FileNotFoundError):
            winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{{{TEST_GUID}}}_is1", 0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY)

    def test_packaged_migration_and_existing_target(self):
        exe = ROOT / f"dist/ValorantToxicTamer-v{VERSION}.exe"
        source = self.root / "legacy" / "data"
        source.mkdir(parents=True)
        (source / "messages.json").write_bytes(b'["old messages"]')
        target = self.root / "migrated" / "data"
        target.parent.mkdir()
        self.run_exe(exe, "--migrate-data", str(source), str(target))
        self.assertEqual((target / "messages.json").read_bytes(), b'["old messages"]')
        self.assertFalse(source.exists())
        source.mkdir()
        (source / "messages.json").write_bytes(b'["new source"]')
        result = subprocess.run([str(exe), "--migrate-data", str(source), str(target)], timeout=60)
        self.assertEqual(result.returncode, 1)
        self.assertEqual((source / "messages.json").read_bytes(), b'["new source"]')
        self.assertEqual((target / "messages.json").read_bytes(), b'["old messages"]')

    def test_installer_migrates_only_with_explicit_consent(self):
        source = self.root / "consented-source" / "data"
        source.mkdir(parents=True)
        (source / "messages.json").write_bytes(b'["installer migration"]')
        install = self.root / "consented-install" / "ValorantToxicTamer"
        self.run_exe(self.setup, "/CURRENTUSER", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
            f"/DIR={install}", f"/DATASOURCE={source}", "/MIGRATEDATA=1")
        try:
            self.assertEqual((install / "data/messages.json").read_bytes(), b'["installer migration"]')
            self.assertFalse(source.exists())
        finally:
            self.run_exe(install / "unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/KEEPDATA=0")
            self.wait_until(lambda: not install.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

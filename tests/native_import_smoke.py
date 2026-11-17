"""Exercise the packaged import entrypoint with disposable Unicode paths."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from valorant_toxic_tamer.app_version import VERSION


class PackagedImportTests(unittest.TestCase):
    def test_packaged_worker_parses_without_ui_or_elevation(self):
        executable = ROOT / "dist" / f"ValorantToxicTamer-v{VERSION}.exe"
        self.assertTrue(executable.is_file(), "Build the current version first")
        with tempfile.TemporaryDirectory(prefix="导入 '&$ ", dir=ROOT / "tests") as directory:
            root = Path(directory)
            source = root / "消息.txt"
            source.write_text("已有\n新增\n新增\n", encoding="utf-8-sig")
            manifest = root / "input.json"
            manifest.write_text(json.dumps({"path": str(source), "existing": ["已有"]}), encoding="utf-8")
            subprocess.run([str(executable), "--import-worker", str(manifest)], check=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            result = json.loads((root / "result.json").read_text(encoding="utf-8"))
            self.assertIsNone(result["error"])
            self.assertEqual(result["messages"], ["已有", "新增", "新增"])
            self.assertEqual(result["unique_messages"], ["新增"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

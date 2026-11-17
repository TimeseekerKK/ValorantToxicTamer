"""Real isolated imports and cancellable blocked readers; no user files."""
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from valorant_toxic_tamer.import_process import prepare_import, worker_command


class ImportProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "中文 '&$.txt"
        self.path.write_text("已有\n新增\n新增\n", encoding="utf-8-sig")

    def test_real_process_preserves_preview_and_deduplication(self):
        preview = prepare_import(self.path, ["已有"])
        self.assertEqual(preview.messages, ("已有", "新增", "新增"))
        self.assertEqual(preview.unique_messages, ("新增",))
        self.assertEqual(preview.duplicate_count, 2)

    def test_blocked_worker_cancels_and_is_reaped(self):
        original = subprocess.Popen
        processes = []
        def spawn(*args, **kwargs):
            process = original(*args, **kwargs)
            processes.append(process)
            return process
        cancel = threading.Event()
        timer = threading.Timer(0.3, cancel.set)
        timer.start()
        try:
            with patch("valorant_toxic_tamer.import_process.worker_command", return_value=[
                    sys.executable, "-B", "-c", "import time; time.sleep(60)"]), patch(
                    "valorant_toxic_tamer.import_process.subprocess.Popen", side_effect=spawn):
                began = time.monotonic()
                with self.assertRaisesRegex(ValueError, "取消"):
                    prepare_import(self.path, (), cancel)
                self.assertLess(time.monotonic() - began, 2)
        finally:
            timer.cancel()
        self.assertTrue(processes)
        self.assertTrue(all(process.poll() is not None for process in processes))

    def test_timeout_and_crash_are_reported(self):
        for command, error in (("import time; time.sleep(60)", "超时"), ("raise SystemExit(3)", "有效结果")):
            with self.subTest(error=error), patch("valorant_toxic_tamer.import_process.worker_command", return_value=[
                    sys.executable, "-B", "-c", command]):
                with self.assertRaisesRegex(ValueError, error):
                    prepare_import(self.path, timeout=0.2)

    def test_precancel_never_spawns_and_frozen_dispatch_is_early(self):
        cancel = threading.Event()
        cancel.set()
        with patch("valorant_toxic_tamer.import_process.subprocess.Popen") as spawn:
            with self.assertRaisesRegex(ValueError, "取消"):
                prepare_import(self.path, cancel=cancel)
            spawn.assert_not_called()
        with patch("sys.frozen", True, create=True):
            self.assertEqual(worker_command(self.path), [sys.executable, "--import-worker", str(self.path)])

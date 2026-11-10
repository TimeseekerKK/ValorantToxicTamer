"""Exercise real disposable workers with simulated streams, never external networking."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from valorant_toxic_tamer.update_process import download_update, download_worker_command
from valorant_toxic_tamer.update_protocol import Release


class DownloadProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="下载 test '&$-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / "installed.exe"
        self.target.write_bytes(b"old program")
        self.content = b"MZ" + b"x" * (512 * 1024)
        self.release = Release("v9.0.0", "https://example.test/exe", len(self.content),
                               "sha256:" + hashlib.sha256(self.content).hexdigest())
        self.cancel = threading.Event()
        self.processes = []
        self.original_popen = subprocess.Popen

    def spawn(self, *args, **kwargs):
        process = self.original_popen(*args, **kwargs)
        self.processes.append(process)
        return process

    def fixture(self, mode):
        code = '''
import io, sys, time
from valorant_toxic_tamer import updater
from valorant_toxic_tamer.update_process import download_worker
mode = sys.argv[2]
class Stream(io.BytesIO):
    def read(self, size=-1):
        if mode == 'blocked' or (mode == 'partial' and self.tell()):
            time.sleep(60)
        if mode == 'partial':
            time.sleep(0.15)
        return super().read(size)
updater._open_update_url = lambda request: Stream(b'MZ' + b'x' * (512 * 1024))
raise SystemExit(download_worker(sys.argv[1]))
'''
        return patch("valorant_toxic_tamer.update_process.download_worker_command",
                     side_effect=lambda manifest: [sys.executable, "-B", "-c", code, str(manifest), mode])

    def tearDown(self):
        for process in self.processes:
            try:
                self.assertIsNotNone(process.poll(), "Owned workers must be reaped")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        self.assertEqual(self.target.read_bytes(), b"old program")

    def test_success_reports_bytes_and_keeps_only_verified_staging_file(self):
        progress = []
        with self.fixture("success"), patch("valorant_toxic_tamer.update_process.subprocess.Popen", side_effect=self.spawn):
            staged = download_update(self.release, self.target, self.cancel,
                                     progress=lambda *args: progress.append(args))
        self.assertEqual(staged.read_bytes(), self.content)
        self.assertEqual(progress[-1], (len(self.content), len(self.content)))
        self.assertEqual(set(self.root.iterdir()), {self.target, staged})

    def test_cancel_interrupts_blocked_read_and_removes_partial_file(self):
        for mode in ("blocked", "partial"):
            self.cancel.clear()
            progress = []

            def cancel_on_progress(received, total):
                progress.append(received)
                if mode == "blocked" or received > 0:
                    self.cancel.set()

            began = time.monotonic()
            with self.subTest(mode=mode), self.fixture(mode), \
                    patch("valorant_toxic_tamer.update_process.subprocess.Popen", side_effect=self.spawn):
                with self.assertRaisesRegex(ValueError, "已取消"):
                    download_update(self.release, self.target, self.cancel, progress=cancel_on_progress)
            self.assertLess(time.monotonic() - began, 3)
            self.assertTrue(progress)
            self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_timeout_and_worker_crash_clean_staging_and_manifest(self):
        with self.fixture("blocked"), patch("valorant_toxic_tamer.update_process.subprocess.Popen", side_effect=self.spawn):
            with self.assertRaisesRegex(ValueError, "超时"):
                download_update(self.release, self.target, self.cancel, timeout=0.2)
        with patch("valorant_toxic_tamer.update_process.download_worker_command",
                   return_value=[sys.executable, "-B", "-c", "raise SystemExit(3)"]), \
                patch("valorant_toxic_tamer.update_process.subprocess.Popen", side_effect=self.spawn):
            with self.assertRaisesRegex(ValueError, "有效结果"):
                download_update(self.release, self.target, self.cancel)
        self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_checksum_failure_is_forwarded_and_cleaned(self):
        release = Release(self.release.version, self.release.url, self.release.size, "sha256:" + "0" * 64)
        with self.fixture("success"), patch("valorant_toxic_tamer.update_process.subprocess.Popen", side_effect=self.spawn):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                download_update(release, self.target, self.cancel)
        self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_precancel_and_spawn_failure_leave_no_staged_file(self):
        self.cancel.set()
        with patch("valorant_toxic_tamer.update_process.subprocess.Popen") as spawn:
            with self.assertRaisesRegex(ValueError, "已取消"):
                download_update(self.release, self.target, self.cancel)
            spawn.assert_not_called()
        self.cancel.clear()
        with patch("valorant_toxic_tamer.update_process.subprocess.Popen", side_effect=OSError("blocked")):
            with self.assertRaisesRegex(OSError, "blocked"):
                download_update(self.release, self.target, self.cancel)
        self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_frozen_worker_uses_early_entrypoint(self):
        with patch("sys.frozen", True, create=True):
            self.assertEqual(download_worker_command(Path("download.json")),
                             [sys.executable, "--download-update-worker", "download.json"])

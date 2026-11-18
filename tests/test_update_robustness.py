"""Retry boundaries, preflight failures and conservative cleanup of owned files."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from valorant_toxic_tamer.updater import download_release
from valorant_toxic_tamer.update_files import cleanup_update_files, mark_task, preflight_download, DAY
from valorant_toxic_tamer.update_protocol import Release


class UpdateRobustnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / "installed.exe"
        self.target.write_bytes(b"original")
        self.content = b"MZ" + b"x" * 300000
        self.release = Release("v9.0.0", "https://example.test/setup", len(self.content),
                               "sha256:" + hashlib.sha256(self.content).hexdigest())

    def test_partial_connection_failure_restarts_without_duplicate_bytes(self):
        class Partial(io.BytesIO):
            def read(stream, size=-1):
                if stream.tell():
                    raise URLError("reset")
                return super().read(size)
        phases, progress = [], []
        cancel = Mock()
        cancel.is_set.return_value = False
        cancel.wait.return_value = False
        with patch("valorant_toxic_tamer.updater._open_update_url", side_effect=[
                Partial(self.content), io.BytesIO(self.content)]) as network:
            staged = download_release(self.release, self.target, cancel,
                progress=lambda received, total: progress.append(received), phase=phases.append)
        self.assertEqual(staged.read_bytes(), self.content)
        self.assertEqual(network.call_count, 2)
        self.assertEqual(phases, ["download", "retry", "download", "verify"])
        self.assertEqual(progress.count(0), 2)
        self.assertEqual(self.target.read_bytes(), b"original")

    def test_integrity_certificate_and_permanent_http_failures_do_not_retry(self):
        for response in (ValueError("证书校验失败"), HTTPError(self.release.url, 404, "missing", {}, None),
                         io.BytesIO(b"MZ" + b"z" * (len(self.content) - 2))):
            kwargs = {"side_effect": response} if isinstance(response, Exception) else {"return_value": response}
            with self.subTest(response=response), patch("valorant_toxic_tamer.updater._open_update_url", **kwargs) as network:
                with self.assertRaises((ValueError, HTTPError)):
                    download_release(self.release, self.target, threading.Event())
                self.assertEqual(network.call_count, 1)
        self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_cancel_during_retry_stops_before_second_request(self):
        cancel = threading.Event()
        def phase(stage):
            if stage == "retry":
                cancel.set()
        with patch("valorant_toxic_tamer.updater._open_update_url", side_effect=URLError("offline")) as network:
            with self.assertRaisesRegex(ValueError, "取消"):
                download_release(self.release, self.target, cancel, phase=phase)
            self.assertEqual(network.call_count, 1)
        self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_disk_space_and_write_access_fail_before_network(self):
        with patch("valorant_toxic_tamer.update_files.shutil.disk_usage", return_value=Mock(free=1)), \
                patch("valorant_toxic_tamer.updater._open_update_url") as network:
            with self.assertRaisesRegex(ValueError, "空间不足"):
                download_release(self.release, self.target, threading.Event())
            network.assert_not_called()
        with patch("valorant_toxic_tamer.update_files.tempfile.TemporaryFile", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(OSError, "无法写入"):
                preflight_download(self.target, 1)

    def task(self, name, *, age=2 * DAY, staged=None, files=()):
        directory = self.root / name
        directory.mkdir()
        mark_task(directory, staged=staged)
        for file in files:
            (directory / file).write_text("fixture")
        for path in directory.iterdir():
            os.utime(path, (10000000 - age, 10000000 - age))
        return directory

    def clean(self):
        cleanup_update_files(self.root, temp_directory=self.root, now=10000000)

    def test_only_expired_inactive_marked_download_is_removed(self):
        staged = self.root / ".vtt-update-old.exe"
        staged.write_bytes(b"partial")
        old = self.task(".vtt-download-old", staged=staged, files=("progress.json",))
        recent = self.task(".vtt-download-new", age=1)
        unknown = self.task(".vtt-download-unknown", files=("personal.txt",))
        unmarked = self.root / ".vtt-download-unmarked"
        unmarked.mkdir()
        with patch("valorant_toxic_tamer.update_files.process_running", return_value=False):
            self.clean()
        self.assertFalse(old.exists())
        self.assertFalse(staged.exists())
        self.assertTrue(all(path.exists() for path in (recent, unknown, unmarked, self.target)))

    def test_active_owner_and_outside_staged_paths_are_preserved(self):
        active = self.task(".vtt-download-active")
        with patch("valorant_toxic_tamer.update_files.process_running", return_value=True):
            self.clean()
        self.assertTrue(active.exists())
        outside = self.task(".vtt-download-outside", staged=self.target)
        with patch("valorant_toxic_tamer.update_files.process_running", return_value=False):
            self.clean()
        self.assertTrue(outside.exists())
        self.assertEqual(self.target.read_bytes(), b"original")

    def test_success_and_error_logs_have_separate_retention(self):
        success = self.task("vtt-updater-success", age=8 * DAY, files=("setup.log",))
        failed = self.task("vtt-updater-failed", age=8 * DAY, files=("error.txt", "setup.log"))
        expired = self.task("vtt-updater-expired", age=31 * DAY, files=("error.txt",))
        with patch("valorant_toxic_tamer.update_files.process_running", return_value=False):
            self.clean()
        self.assertFalse(success.exists())
        self.assertFalse(expired.exists())
        self.assertTrue(failed.exists())

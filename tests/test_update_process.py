"""Transient update subprocess results, cancellation and resource cleanup."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from valorant_toxic_tamer.update_process import check_for_update, check_worker, worker_command
from valorant_toxic_tamer.update_protocol import Release


class UpdateProcessTests(unittest.TestCase):
    def setUp(self):
        self.cancel = threading.Event()
        self.processes = []
        self.outputs = []
        self.original_popen = subprocess.Popen

    def spawn(self, *args, **kwargs):
        process = self.original_popen(*args, **kwargs)
        self.processes.append(process)
        return process

    def fixture(self, code):
        def command(channel, result_path):
            self.assertEqual(channel, "beta")
            self.outputs.append(result_path)
            return [sys.executable, "-c", code, str(result_path)]
        return patch("valorant_toxic_tamer.update_process.worker_command", side_effect=command)

    def tearDown(self):
        for process in self.processes:
            try:
                self.assertIsNotNone(process.poll(), "Worker must be reaped before returning")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        for path in self.outputs:
            self.assertFalse(path.parent.exists(), "Temporary worker results must be removed")

    def test_valid_result_and_no_update_release_resources(self):
        for value in (None, {"version": "v9.0.0", "url": "https://example.test/file.exe",
                             "size": 5, "digest": None}):
            code = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(" + repr(
                json.dumps({"release": value, "error": None})) + ",encoding='utf-8')"
            with self.fixture(code), patch("valorant_toxic_tamer.update_process.subprocess.Popen", side_effect=self.spawn):
                result = check_for_update(channel="beta", cancel=self.cancel)
            self.assertEqual(result, Release(**value) if value else None)

    def test_errors_and_invalid_results_release_resources(self):
        for payload, message in (({"error": "HTTPS 证书校验失败", "release": None}, "HTTPS"),
                                 ([], "未返回有效结果"), ("bad json", "未返回有效结果")):
            content = json.dumps(payload, ensure_ascii=False) if payload != "bad json" else payload
            code = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(" + repr(content) + ",encoding='utf-8')"
            with self.fixture(code), patch("valorant_toxic_tamer.update_process.subprocess.Popen", side_effect=self.spawn):
                with self.assertRaisesRegex(ValueError, message):
                    check_for_update(channel="beta", cancel=self.cancel)
        with self.fixture("raise SystemExit(3)"), patch(
                "valorant_toxic_tamer.update_process.subprocess.Popen", side_effect=self.spawn):
            with self.assertRaisesRegex(ValueError, "未返回有效结果"):
                check_for_update(channel="beta", cancel=self.cancel)

    def test_timeout_terminates_and_reaps_owned_worker(self):
        with self.fixture("import time; time.sleep(60)"), patch(
                "valorant_toxic_tamer.update_process.subprocess.Popen", side_effect=self.spawn):
            with self.assertRaisesRegex(ValueError, "超时"):
                check_for_update(channel="beta", cancel=self.cancel, timeout=0.15)

    def test_cancellation_terminates_and_reaps_owned_worker(self):
        timer = threading.Timer(0.15, self.cancel.set)
        timer.start()
        try:
            with self.fixture("import time; time.sleep(60)"), patch(
                    "valorant_toxic_tamer.update_process.subprocess.Popen", side_effect=self.spawn):
                with self.assertRaisesRegex(ValueError, "已取消"):
                    check_for_update(channel="beta", cancel=self.cancel)
        finally:
            timer.join()
        with patch("valorant_toxic_tamer.update_process.subprocess.Popen") as spawn:
            with self.assertRaisesRegex(ValueError, "已取消"):
                check_for_update(channel="beta", cancel=self.cancel)
            spawn.assert_not_called()

    def test_worker_reuses_frozen_bundle_without_reset_environment(self):
        code = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('{\"error\":null,\"release\":null}')"
        with self.fixture(code), patch.dict(os.environ, {"PYINSTALLER_RESET_ENVIRONMENT": "1"}), patch(
                "valorant_toxic_tamer.update_process.subprocess.Popen", side_effect=self.spawn) as spawn:
            self.assertIsNone(check_for_update(channel="beta", cancel=self.cancel))
            self.assertNotIn("PYINSTALLER_RESET_ENVIRONMENT", spawn.call_args.kwargs["env"])
        with patch("sys.frozen", True, create=True):
            self.assertEqual(worker_command("beta", Path("result.json")),
                             [sys.executable, "--check-update-worker", "beta", "result.json"])

    def test_worker_serializes_success_and_network_failure(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            result_path = Path(directory) / "result.json"
            release = Release("v9.0.0", "https://example.test/file.exe", 5, None)
            with patch("valorant_toxic_tamer.updater.latest_release", return_value=release):
                self.assertEqual(check_worker("beta", result_path), 0)
                self.assertEqual(json.loads(result_path.read_text(encoding="utf-8"))["release"]["version"], "v9.0.0")
            with patch("valorant_toxic_tamer.updater.latest_release", side_effect=OSError("offline")):
                self.assertEqual(check_worker("beta", result_path), 1)
                self.assertEqual(json.loads(result_path.read_text(encoding="utf-8"))["error"], "offline")

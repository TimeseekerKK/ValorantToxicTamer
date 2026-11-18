import hashlib
import io
import json
import ssl
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import truststore

from valorant_toxic_tamer.updater import (EXE_NAME, MANIFEST_URL, REPOSITORY, Release, download_release,
                     installed_executable, latest_release, launch_installer, version_tuple)


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.target = self.directory / "当前程序.exe"
        self.target.write_bytes(b"old program")
        self.content = b"MZ" + b"new exe" * 100
        self.url = f"https://github.com/{REPOSITORY}/releases/download/v1.1.0/ValorantToxicTamer-Setup-v1.1.0.exe"
        self.asset = dict(name="ValorantToxicTamer-Setup-v1.1.0.exe", state="uploaded", size=len(self.content),
                          browser_download_url=self.url,
                          digest="sha256:" + hashlib.sha256(self.content).hexdigest())
        self.payload = dict(tag_name="v1.1.0", prerelease=False, draft=False, assets=[self.asset])
        self.release = Release("v1.1.0", self.url, len(self.content), self.asset["digest"])

    def manifest(self, beta=None):
        def entry(payload):
            asset = payload["assets"][0]
            return dict(version=payload["tag_name"], url=asset["browser_download_url"],
                        size=asset["size"], digest=asset["digest"])
        return {"schema": 1, "channels": {"stable": entry(self.payload), "beta": beta}}

    def lookup(self, current="1.0.0", *, channel="stable", beta=None):
        response = io.BytesIO(json.dumps(self.manifest(beta)).encode())
        with patch("valorant_toxic_tamer.updater.urlopen", return_value=response) as request:
            result = latest_release(current, channel=channel)
        self.assertEqual(request.call_args.args[0].full_url, MANIFEST_URL)
        self.assertNotIn("api.github.com", request.call_args.args[0].full_url)
        self.assert_verified_context(request)
        return result

    def assert_verified_context(self, request):
        context = request.call_args.kwargs["context"]
        self.assertIsInstance(context, truststore.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_numeric_version_comparison_and_tag_formats(self):
        self.assertGreater(version_tuple("v1.10.0"), version_tuple("1.9.9"))
        self.assertEqual(version_tuple("V1.0"), version_tuple("1.0.0"))
        versions = ("1.2.0-beta", "1.2.0-beta.1", "1.2.0-beta.2", "1.2.0-beta.10",
                    "1.2.0", "1.2.1-beta.1")
        for older, newer in zip(versions, versions[1:]):
            self.assertLess(version_tuple(older), version_tuple(newer))
        for invalid in ("", "latest", "1.2.3.4", "1.2.3-beta.0", "1.2.3-beta.x", "1.2.3-rc.1"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                version_tuple(invalid)

    def beta_entry(self, tag):
        item = self.manifest()["channels"]["stable"].copy()
        item["version"] = tag
        item["url"] = f"https://github.com/{REPOSITORY}/releases/download/{tag}/ValorantToxicTamer-Setup-{tag}.exe"
        return item

    def test_beta_can_switch_back_to_latest_stable_but_stable_never_downgrades(self):
        self.assertEqual(self.lookup("1.1.0-beta.2"), self.release)
        self.assertEqual(self.lookup("1.2.0-beta.1"), self.release)
        self.assertIsNone(self.lookup("1.2.0"))

    def test_channels_choose_highest_version_and_stable_ignores_beta(self):
        beta = self.beta_entry("v1.2.0-beta.10")
        self.assertEqual(self.lookup(channel="beta", beta=beta).version, beta["version"])
        self.assertEqual(self.lookup(beta=beta), self.release)
        self.assertIsNone(self.lookup("1.2.0", channel="beta", beta=beta))
        self.assertEqual(self.lookup(channel="beta"), self.release)
        self.assertEqual(self.lookup(channel="beta", beta=self.beta_entry("v1.1.0-beta.10")), self.release)

    def test_newer_release_and_same_version(self):
        self.assertEqual(self.lookup(), self.release)
        self.assertIsNone(self.lookup("1.1.0"))

    def test_invalid_channel_does_not_make_network_request(self):
        with patch("valorant_toxic_tamer.updater.urlopen") as network:
            with self.assertRaisesRegex(ValueError, "渠道"):
                latest_release(channel="unknown")
            network.assert_not_called()

    def test_invalid_manifests_are_rejected_before_install(self):
        import copy
        payload = self.manifest()
        variants = [[], {}, dict(payload, schema=2), dict(payload, schema=True)]
        for field, values in {"version": [None, "v9.0.0-beta.1", "invalid"],
                              "url": [None, "http://github.com/file.exe", self.url + "?redirect=1",
                                      self.url.replace("github.com", "evil.test"),
                                      self.url.replace("Setup-v1.1.0", "v1.1.0")],
                              "size": [0, True, "5"], "digest": [None, "sha256:bad"]}.items():
            for value in values:
                bad = copy.deepcopy(payload)
                bad["channels"]["stable"][field] = value
                variants.append(bad)
        for value in variants:
            with self.subTest(value=value), patch("valorant_toxic_tamer.updater.urlopen",
                    return_value=io.BytesIO(json.dumps(value).encode())), self.assertRaises(ValueError):
                latest_release("1.0.0")

    def test_http_errors_are_actionable_and_do_not_retry(self):
        for code in (404, 403, 429, 500):
            with patch("valorant_toxic_tamer.updater.urlopen",
                       side_effect=HTTPError(MANIFEST_URL, code, "error", {}, None)) as network:
                with self.assertRaisesRegex(ValueError, "下载页"):
                    latest_release()
                network.assert_called_once()

    def test_connection_failure_retries_once_and_then_reports_failure(self):
        with patch("valorant_toxic_tamer.updater.urlopen", side_effect=URLError("offline")) as network, \
                patch("valorant_toxic_tamer.updater.time.sleep"):
            with self.assertRaisesRegex(ValueError, "连接更新服务"):
                latest_release()
            self.assertEqual(network.call_count, 2)
        with patch("valorant_toxic_tamer.updater.urlopen", side_effect=[URLError("offline"),
                io.BytesIO(json.dumps(self.manifest()).encode())]), patch("valorant_toxic_tamer.updater.time.sleep"):
            self.assertEqual(latest_release("1.0.0"), self.release)

    def test_malformed_and_oversized_documents_are_not_used(self):
        for raw in (b"<html>failure</html>", b"x" * 65537):
            with patch("valorant_toxic_tamer.updater.urlopen", return_value=io.BytesIO(raw)), self.assertRaises(ValueError):
                latest_release()

    def test_cache_reuses_valid_manifest_across_channels_and_expires(self):
        cache = self.directory / "cache.json"
        content = json.dumps(self.manifest(self.beta_entry("v1.2.0-beta.1"))).encode()
        with patch("valorant_toxic_tamer.updater.time.time", return_value=1000), patch(
                "valorant_toxic_tamer.updater.urlopen", return_value=io.BytesIO(content)) as network:
            self.assertEqual(latest_release("1.0.0", cache_path=cache), self.release)
            self.assertEqual(latest_release("1.0.0", channel="beta", cache_path=cache).version, "v1.2.0-beta.1")
            network.assert_called_once()
        with patch("valorant_toxic_tamer.updater.time.time", return_value=1301), patch(
                "valorant_toxic_tamer.updater.urlopen", side_effect=HTTPError(MANIFEST_URL, 503, "error", {}, None)):
            with self.assertRaises(ValueError):
                latest_release("1.0.0", cache_path=cache)
        # An expired cache must never become a successful 'latest version' result.
        self.assertTrue(cache.exists())

    def test_corrupt_cache_or_unwritable_cache_does_not_prevent_network_check(self):
        cache = self.directory / "cache.json"
        cache.write_text("bad", encoding="utf-8")
        with patch("valorant_toxic_tamer.updater.urlopen", return_value=io.BytesIO(json.dumps(self.manifest()).encode())), \
                patch("valorant_toxic_tamer.updater.atomic_json", side_effect=PermissionError("read-only")):
            self.assertEqual(latest_release("1.0.0", cache_path=cache), self.release)

    def test_download_checks_bytes_and_preserves_installed_file(self):
        with patch("valorant_toxic_tamer.updater.urlopen", return_value=io.BytesIO(self.content)) as request:
            staged = download_release(self.release, self.target, threading.Event())
        self.assert_verified_context(request)
        self.assertEqual(staged.parent, self.target.parent)
        self.assertEqual(staged.read_bytes(), self.content)
        self.assertEqual(self.target.read_bytes(), b"old program")

    def test_certificate_failures_are_explained_without_insecure_retry(self):
        certificate_error = ssl.SSLCertVerificationError(1, "unable to get issuer certificate")
        for error in (certificate_error, URLError(certificate_error)):
            with self.subTest(error=error):
                with patch("valorant_toxic_tamer.updater.urlopen", side_effect=error) as request:
                    with self.assertRaisesRegex(ValueError, "HTTPS 证书校验失败"):
                        latest_release("1.0.0")
                request.assert_called_once()
                self.assert_verified_context(request)
                with patch("valorant_toxic_tamer.updater.urlopen", side_effect=error) as request:
                    with self.assertRaisesRegex(ValueError, "HTTPS 证书校验失败"):
                        download_release(self.release, self.target, threading.Event())
                request.assert_called_once()
                self.assert_verified_context(request)
                self.assertEqual(list(self.directory.iterdir()), [self.target])
                self.assertEqual(self.target.read_bytes(), b"old program")

    def test_corrupt_truncated_oversized_non_exe_downloads_are_cleaned(self):
        for content in (self.content[:-1], self.content + b"X", b"MZ" + b"X" * (len(self.content)-2)):
            with patch("valorant_toxic_tamer.updater.urlopen", return_value=io.BytesIO(content)):
                with self.assertRaises(ValueError):
                    download_release(self.release, self.target, threading.Event())
            self.assertEqual(list(self.directory.iterdir()), [self.target])
        with patch("valorant_toxic_tamer.updater.urlopen", return_value=io.BytesIO(b"HTML")):
            with self.assertRaisesRegex(ValueError, "EXE"):
                download_release(Release("1.1.0", self.url, 4, None), self.target, threading.Event())

    def test_missing_digest_uses_size_and_exe_check(self):
        self.asset["digest"] = None
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.lookup()
        # Legacy download fixtures remain compatible; new feeds always require a digest.
        release = Release(self.release.version, self.url, len(self.content), None)
        with patch("valorant_toxic_tamer.updater.urlopen", return_value=io.BytesIO(self.content)):
            self.assertTrue(download_release(release, self.target, threading.Event()).exists())

    def test_network_failure_and_cancel_never_modify_current_exe(self):
        with patch("valorant_toxic_tamer.updater.urlopen", side_effect=URLError("offline")):
            with self.assertRaises(URLError):
                download_release(self.release, self.target, threading.Event())
        cancel = threading.Event()
        cancel.set()
        with patch("valorant_toxic_tamer.updater.urlopen") as network:
            with self.assertRaisesRegex(ValueError, "取消"):
                download_release(self.release, self.target, cancel)
            network.assert_not_called()
        self.assertEqual(list(self.directory.iterdir()), [self.target])
        self.assertEqual(self.target.read_bytes(), b"old program")

    def test_source_cannot_overwrite_python(self):
        with patch("valorant_toxic_tamer.updater.sys.frozen", False, create=True):
            with self.assertRaisesRegex(ValueError, "打包"):
                installed_executable()

    def test_launcher_failure_keeps_current_exe_and_removes_helper(self):
        staged = self.directory / "staged.exe"
        staged.write_bytes(self.content)
        helper = self.directory / "helper"
        helper.mkdir()
        with patch("valorant_toxic_tamer.updater.tempfile.mkdtemp", return_value=str(helper)), \
                patch("valorant_toxic_tamer.updater.subprocess.Popen", side_effect=OSError("blocked")):
            with self.assertRaisesRegex(OSError, "blocked"):
                launch_installer(staged, self.target)
        self.assertFalse(helper.exists())
        self.assertEqual(self.target.read_bytes(), b"old program")

    def test_launcher_handshake_and_independent_frozen_restart_environment(self):
        staged = self.directory / "staged.exe"
        staged.write_bytes(self.content)
        helper = self.directory / "helper"
        helper.mkdir()
        import os
        process = Mock(pid=os.getpid())
        def spawn(*args, **kwargs):
            (helper / "ready").touch()
            return process
        with patch("valorant_toxic_tamer.updater.tempfile.mkdtemp", return_value=str(helper)), \
                patch("valorant_toxic_tamer.updater.subprocess.Popen", side_effect=spawn) as popen:
            self.assertIs(launch_installer(staged, self.target), process)
        self.assertEqual(popen.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertTrue((helper / "proceed").exists())
        manifest = json.loads((helper / "update.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(manifest["target"], str(self.target))
        self.assertEqual(manifest["sha256"], hashlib.sha256(self.content).hexdigest())


if __name__ == "__main__":
    unittest.main()

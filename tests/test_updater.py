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

from valorant_toxic_tamer.updater import (EXE_NAME, LATEST_URL, RELEASES_URL, REPOSITORY, Release, download_release,
                     installed_executable, latest_release, launch_installer, version_tuple)


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.target = self.directory / "当前程序.exe"
        self.target.write_bytes(b"old program")
        self.content = b"MZ" + b"new exe" * 100
        self.url = f"https://github.com/{REPOSITORY}/releases/download/v1.1.0/{EXE_NAME}"
        self.asset = dict(name=EXE_NAME, state="uploaded", size=len(self.content),
                          browser_download_url=self.url,
                          digest="sha256:" + hashlib.sha256(self.content).hexdigest())
        self.payload = dict(tag_name="v1.1.0", prerelease=False, draft=False, assets=[self.asset])
        self.release = Release("v1.1.0", self.url, len(self.content), self.asset["digest"])

    def lookup(self, current="1.0.0"):
        response = io.BytesIO(json.dumps(self.payload).encode())
        with patch("valorant_toxic_tamer.updater.urlopen", return_value=response) as request:
            result = latest_release(current)
        self.assertEqual(request.call_args.args[0].full_url, LATEST_URL)
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

    def test_beta_can_switch_back_to_latest_stable_but_stable_never_downgrades(self):
        self.assertEqual(self.lookup("1.1.0-beta.2"), self.release)
        self.assertEqual(self.lookup("1.2.0-beta.1"), self.release)
        self.assertIsNone(self.lookup("1.2.0"))

    def beta_lookup(self, releases, current="1.0.0"):
        response = io.BytesIO(json.dumps(releases).encode())
        with patch("valorant_toxic_tamer.updater.urlopen", return_value=response) as request:
            result = latest_release(current, channel="beta")
        self.assertEqual(request.call_args.args[0].full_url, f"{RELEASES_URL}?per_page=100&page=1")
        self.assert_verified_context(request)
        return result

    def test_beta_channel_compares_numeric_versions_and_excludes_drafts_and_other_previews(self):
        releases = [dict(self.payload, tag_name="v1.2.0-beta.2", prerelease=True),
                    dict(self.payload, tag_name="v1.2.0-beta.10", prerelease=True),
                    dict(self.payload, tag_name="v9.0.0-beta.1", prerelease=True, draft=True),
                    dict(self.payload, tag_name="v9.0.0-rc.1", prerelease=True),
                    dict(self.payload, tag_name="invalid"), dict(self.payload, tag_name=None),
                    dict(self.payload, tag_name="v8.0.0", prerelease=True),
                    dict(self.payload, tag_name="v8.0.0-beta.1", prerelease=False), self.payload]
        self.assertEqual(self.beta_lookup(releases).version, "v1.2.0-beta.10")
        self.assertIsNone(self.beta_lookup(releases, current="1.2.0"))

    def test_beta_channel_prefers_same_base_stable_and_falls_back_to_stable(self):
        releases = [dict(self.payload, tag_name="v1.1.0-beta.10", prerelease=True), self.payload]
        self.assertEqual(self.beta_lookup(releases), self.release)
        self.assertEqual(self.beta_lookup([self.payload]), self.release)
        self.assertIsNone(self.beta_lookup([self.payload], current="1.1.0"))

    def test_beta_channel_reads_all_pages_before_selecting_newest_version(self):
        pages = [io.BytesIO(json.dumps([self.payload] * 100).encode()),
                 io.BytesIO(json.dumps([dict(self.payload, tag_name="v1.3.0-beta.1", prerelease=True)]).encode())]
        with patch("valorant_toxic_tamer.updater.urlopen", side_effect=pages) as request:
            result = latest_release("1.0.0", channel="beta")
        self.assertEqual(result.version, "v1.3.0-beta.1")
        self.assertEqual([call.args[0].full_url for call in request.call_args_list],
                         [f"{RELEASES_URL}?per_page=100&page={page}" for page in (1, 2)])

    def test_invalid_channel_empty_beta_and_malformed_response_are_reported(self):
        with patch("valorant_toxic_tamer.updater.urlopen") as network:
            with self.assertRaisesRegex(ValueError, "渠道"):
                latest_release(channel="unknown")
            network.assert_not_called()
        for payload in ([], [dict(self.payload, draft=True)], {}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.beta_lookup(payload)

    def test_newer_release_selects_expected_exe(self):
        self.payload["assets"] += [dict(self.asset, name="uninstaller.exe"),
                                  dict(self.asset, name="source.zip")]
        self.assertEqual(self.lookup(), self.release)

    def test_same_and_older_versions_are_not_installed(self):
        for tag in ("v1.0.0", "v0.9.9", "v1.0"):
            self.payload.update(tag_name=tag, assets=[])
            self.assertIsNone(self.lookup())

    def test_single_versioned_exe_is_supported(self):
        self.asset["name"] = "ValorantToxicTamer-v1.1.0.exe"
        self.assertEqual(self.lookup(), self.release)

    def test_missing_or_ambiguous_exe_is_reported(self):
        for assets in ([], [dict(self.asset, name="source.zip")],
                       [dict(self.asset, name="x64.exe"), dict(self.asset, name="arm64.exe")]):
            self.payload["assets"] = assets
            with self.assertRaisesRegex(ValueError, "EXE"):
                self.lookup()

    def test_unpublished_and_prerelease_are_rejected(self):
        for key in ("draft", "prerelease"):
            self.payload[key] = True
            with self.assertRaisesRegex(ValueError, "正式"):
                self.lookup()
            self.payload[key] = False

    def test_non_repository_url_and_invalid_size_digest_are_rejected(self):
        for url in ("http://github.com/other", "https://evil.example/file.exe",
                    "https://github.com/another/repo/releases/download/a/b.exe"):
            self.asset["browser_download_url"] = url
            with self.assertRaisesRegex(ValueError, "地址"):
                self.lookup()
        self.asset["browser_download_url"] = self.url
        self.asset["size"] = 0
        with self.assertRaisesRegex(ValueError, "大小"):
            self.lookup()
        self.asset["size"] = 1
        self.asset["digest"] = "sha256:bad"
        with self.assertRaisesRegex(ValueError, "校验"):
            self.lookup()

    def test_no_release_and_rate_limit_messages(self):
        for code, message in ((404, "Release"), (403, "受限"), (429, "受限")):
            with patch("valorant_toxic_tamer.updater.urlopen", side_effect=HTTPError(LATEST_URL, code, "error", {}, None)):
                with self.assertRaisesRegex(ValueError, message):
                    latest_release()

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
        release = self.lookup()
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
        process = Mock()
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

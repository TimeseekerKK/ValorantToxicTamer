"""Published assets, channel selection and fail-closed feed generation."""
import unittest
from unittest.mock import patch

from scripts.publish_update_manifest import build_manifest, publish
from valorant_toxic_tamer.update_settings import REPOSITORY


def release(tag, *, draft=False):
    return {"tag_name": tag, "draft": draft, "prerelease": "-beta" in tag, "assets": [{
        "name": f"ValorantToxicTamer-Setup-{tag}.exe", "state": "uploaded", "size": 123,
        "browser_download_url": f"https://github.com/{REPOSITORY}/releases/download/{tag}/ValorantToxicTamer-Setup-{tag}.exe",
        "digest": "sha256:" + "a" * 64,
    }]}


class PublishManifestTests(unittest.TestCase):
    def test_numeric_channels_and_drafts(self):
        items = [release("v1.9.0"), release("v1.10.0"), release("v1.11.0-beta.2"),
                 release("v1.11.0-beta.10"), release("v99.0.0", draft=True), {"tag_name": "nightly"}]
        payload = build_manifest(items)
        self.assertEqual(payload["channels"]["stable"]["version"], "v1.10.0")
        self.assertEqual(payload["channels"]["beta"]["version"], "v1.11.0-beta.10")
        self.assertIsNone(build_manifest([release("v1.0.0")])["channels"]["beta"])

    def test_latest_missing_asset_does_not_silently_publish_old_version(self):
        newest = release("v1.1.0")
        newest["assets"] = []
        with self.assertRaisesRegex(ValueError, "安装包"):
            build_manifest([release("v1.0.0"), newest])
        newest["assets"] = [release("v1.1.0")["assets"][0]] * 2
        with self.assertRaises(ValueError):
            build_manifest([newest])

    def test_digest_is_required_or_calculated_from_downloaded_asset(self):
        item = release("v1.0.0")
        item["assets"][0]["digest"] = None
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            build_manifest([item])
        expected = "sha256:" + "b" * 64
        self.assertEqual(build_manifest([item], lambda tag, asset: expected)["channels"]["stable"]["digest"], expected)

    def test_invalid_channel_and_untrusted_download_are_rejected(self):
        item = release("v1.0.0")
        item["prerelease"] = True
        with self.assertRaisesRegex(ValueError, "渠道"):
            build_manifest([item])
        item = release("v1.0.0")
        item["assets"][0]["browser_download_url"] = "https://evil.test/setup.exe"
        with self.assertRaises(ValueError):
            build_manifest([item])
        with self.assertRaisesRegex(ValueError, "正式版"):
            build_manifest([release("v1.1.0-beta.1")])

    def test_publish_rejects_stale_feed_before_writing_or_pushing(self):
        import json
        sha = "a" * 40
        previous = build_manifest([release("v1.1.0")])
        outputs = [f"https://github.com/{REPOSITORY}.git", f"{sha}\trefs/heads/gh-pages", "", sha, json.dumps(previous)]
        with patch("scripts.publish_update_manifest.run", side_effect=outputs) as command:
            with self.assertRaisesRegex(ValueError, "落后"):
                publish(build_manifest([release("v1.0.0")]))
            self.assertFalse(any(call.args[0][1] == "push" for call in command.call_args_list))


if __name__ == "__main__":
    unittest.main()

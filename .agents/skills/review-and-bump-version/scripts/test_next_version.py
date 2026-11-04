"""Release numbering and read-only preflight regression tests; no network calls."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import next_version as nv

SHA = "a" * 40
OTHER = "b" * 40


def snapshot(branch="main", stable="v1.2.3", betas=()):
    tags = [stable, *betas]
    return {
        "branch": branch, "repository": nv.REPOSITORY, "local_tags": {},
        "remote_tags": {tag: SHA for tag in tags},
        "releases": [{"tag_name": tag, "name": tag.split("-beta")[0],
                      "draft": False, "prerelease": "-beta" in tag} for tag in tags],
    }


class NumberingTests(unittest.TestCase):
    def test_stable_severity_and_reset(self):
        for level, expected in (("major", "v2.0.0"), ("minor", "v1.3.0"), ("patch", "v1.2.4")):
            with self.subTest(level=level):
                result = nv.plan(snapshot(), "1.2.3", level=level)
                self.assertEqual(result["tag"], expected)
                self.assertFalse(result["prerelease"])
                self.assertTrue(result["latest"])

    def test_patch_has_no_decimal_carry(self):
        self.assertEqual(nv.plan(snapshot(stable="v1.2.9"), "1.2.9", level="patch")["tag"], "v1.2.10")

    def test_open_beta_respects_severity(self):
        for level, expected in (("patch", "v1.2.4-beta.1"), ("minor", "v1.3.0-beta.1"), ("major", "v2.0.0-beta.1")):
            with self.subTest(level=level):
                result = nv.plan(snapshot("Beta"), "1.2.3", level=level)
                self.assertEqual(result["tag"], expected)
                self.assertEqual(result["version"], expected[1:])
                self.assertEqual(result["title"], expected.split("-beta")[0])
                self.assertTrue(result["prerelease"])
                self.assertFalse(result["latest"])

    def test_continue_beta_only_increments_sequence(self):
        data = snapshot("Beta", betas=["v1.3.0-beta.1"])
        self.assertEqual(nv.plan(data, "1.3.0-beta.1", level="patch")["tag"], "v1.3.0-beta.2")

    def test_beta_sequence_sorts_numerically(self):
        data = snapshot("Beta", betas=["v1.3.0-beta.9"])
        self.assertEqual(nv.plan(data, "1.3.0-beta.9", level="patch")["tag"], "v1.3.0-beta.10")

    def test_higher_severity_opens_new_line(self):
        data = snapshot("Beta", betas=["v1.2.4-beta.2"])
        self.assertEqual(nv.plan(data, "1.2.4-beta.2", level="minor")["tag"], "v1.3.0-beta.1")

    def test_same_severity_keeps_planned_feature_base(self):
        data = snapshot("Beta", betas=["v1.3.0-beta.2"])
        self.assertEqual(nv.plan(data, "1.3.0-beta.2", level="minor")["tag"], "v1.3.0-beta.3")

    def test_closed_beta_line_starts_next_version(self):
        data = snapshot("Beta", stable="v1.3.0", betas=["v1.3.0-beta.2"])
        self.assertEqual(nv.plan(data, "1.3.0-beta.2", level="patch")["tag"], "v1.3.1-beta.1")

    def test_legacy_bare_beta_migrates_to_sequence_one(self):
        data = snapshot("Beta", betas=["v1.3.0-beta"])
        self.assertEqual(nv.plan(data, "1.3.0", level="patch")["tag"], "v1.3.0-beta.1")

    def test_draft_and_local_tags_are_not_stable_baselines(self):
        data = snapshot()
        data["remote_tags"]["v9.0.0"] = SHA
        data["local_tags"]["v10.0.0"] = SHA
        data["releases"].append(dict(tag_name="v9.0.0", name="v9.0.0", draft=True, prerelease=False))
        self.assertEqual(nv.plan(data, "1.2.3", level="patch")["tag"], "v1.2.4")

    def test_unpublished_beta_tag_reserves_sequence(self):
        data = snapshot("Beta", betas=["v1.3.0-beta.1"])
        data["local_tags"]["v1.3.0-beta.2"] = SHA
        self.assertEqual(nv.plan(data, "1.3.0-beta.1", level="patch")["tag"], "v1.3.0-beta.3")

    def test_foreign_tags_do_not_change_numbering(self):
        data = snapshot()
        data["remote_tags"].update({"nightly-99": SHA, "v99.0": SHA, "v99.0.0-alpha.1": SHA})
        self.assertEqual(nv.plan(data, "1.2.3", level="patch")["tag"], "v1.2.4")

    def test_promotion_keeps_base_without_double_increment(self):
        data = snapshot(betas=["v1.3.0-beta.2"])
        result = nv.plan(data, "1.3.0-beta.2", promote="v1.3.0-beta.2")
        self.assertEqual(result["tag"], "v1.3.0")
        self.assertEqual(result["promotion_source"]["commit"], SHA)
        self.assertFalse(result["prerelease"])

    def test_closed_line_cannot_be_promoted(self):
        data = snapshot(stable="v1.3.0", betas=["v1.3.0-beta.2"])
        with self.assertRaisesRegex(ValueError, "closed"):
            nv.plan(data, "1.3.0", promote="v1.3.0-beta.2")

    def test_promotion_requires_published_candidate(self):
        with self.assertRaisesRegex(ValueError, "published Beta"):
            nv.plan(snapshot(), "1.2.3", promote="v1.3.0-beta.1")

    def test_resume_does_not_increment(self):
        data = snapshot("Beta")
        data["remote_tags"]["v1.3.0-beta.1"] = SHA
        data["releases"].append(dict(tag_name="v1.3.0-beta.1", name="v1.3.0", draft=True, prerelease=True))
        result = nv.plan(data, "1.3.0-beta.1", resume="v1.3.0-beta.1", expected_commit=SHA)
        self.assertEqual(result["tag"], "v1.3.0-beta.1")
        self.assertEqual(result["status"], "draft")

    def test_resume_published_reports_state(self):
        data = snapshot("Beta", betas=["v1.3.0-beta.1"])
        self.assertEqual(nv.plan(data, "1.3.0-beta.1", resume="v1.3.0-beta.1", expected_commit=SHA)["status"], "published")

    def test_resume_rejects_wrong_commit(self):
        data = snapshot("Beta", betas=["v1.3.0-beta.1"])
        with self.assertRaisesRegex(ValueError, "different commit"):
            nv.plan(data, "1.3.0-beta.1", resume="v1.3.0-beta.1", expected_commit=OTHER)

    def test_resume_reserved_tag_requires_commit(self):
        data = snapshot("Beta", betas=["v1.3.0-beta.1"])
        with self.assertRaisesRegex(ValueError, "expected-commit"):
            nv.plan(data, "1.3.0-beta.1", resume="v1.3.0-beta.1")

    def test_stale_baseline_stops(self):
        with self.assertRaisesRegex(ValueError, "baseline"):
            nv.plan(snapshot(), "1.2.2", level="patch")
        with self.assertRaisesRegex(ValueError, "baseline"):
            nv.plan(snapshot("Beta", betas=["v1.3.0-beta.2"]), "1.2.3", level="patch")

    def test_tag_collision_stops(self):
        data = snapshot()
        data["local_tags"]["v1.2.4"] = SHA
        with self.assertRaisesRegex(ValueError, "reserved"):
            nv.plan(data, "1.2.3", level="patch")

    def test_local_remote_tag_disagreement_stops(self):
        data = snapshot()
        data["local_tags"]["v1.2.3"] = OTHER
        with self.assertRaisesRegex(ValueError, "disagree"):
            nv.plan(data, "1.2.3", level="patch")

    def test_unfinished_batch_requires_resume(self):
        with self.assertRaisesRegex(ValueError, "resume"):
            nv.plan(snapshot("Beta"), "1.3.0-beta.1", level="patch")

    def test_bad_release_state_stops(self):
        data = snapshot()
        data["releases"][0]["prerelease"] = True
        with self.assertRaisesRegex(ValueError, "channel"):
            nv.plan(data, "1.2.3", level="patch")

    def test_no_stable_release_stops(self):
        data = snapshot()
        data["releases"] = []
        with self.assertRaisesRegex(ValueError, "No published stable"):
            nv.plan(data, "1.2.3", level="patch")

    def test_closed_beta_draft_cannot_be_published_by_resume(self):
        data = snapshot("Beta", stable="v1.3.0")
        data["remote_tags"]["v1.3.0-beta.2"] = SHA
        data["releases"].append(dict(tag_name="v1.3.0-beta.2", name="v1.3.0", draft=True, prerelease=True))
        with self.assertRaisesRegex(ValueError, "closed"):
            nv.plan(data, "1.3.0-beta.2", resume="v1.3.0-beta.2", expected_commit=SHA)

    def test_resume_wrong_title_stops(self):
        data = snapshot("Beta", betas=["v1.3.0-beta.2"])
        data["releases"][-1]["name"] = "v1.3.0-beta.2"
        with self.assertRaisesRegex(ValueError, "title/channel"):
            nv.plan(data, "1.3.0-beta.2", resume="v1.3.0-beta.2", expected_commit=SHA)

    def test_resume_other_channel_stops(self):
        with self.assertRaisesRegex(ValueError, "another channel"):
            nv.plan(snapshot(), "1.2.3", resume="v1.3.0-beta.2")

    def test_promotion_does_not_accept_a_draft(self):
        data = snapshot(betas=["v1.3.0-beta.2"])
        data["releases"][-1]["draft"] = True
        with self.assertRaisesRegex(ValueError, "published Beta"):
            nv.plan(data, "1.2.3", promote="v1.3.0-beta.2")

    def test_promotion_cannot_override_a_reserved_stable_tag(self):
        data = snapshot(betas=["v1.3.0-beta.2"])
        data["remote_tags"]["v1.3.0"] = OTHER
        with self.assertRaisesRegex(ValueError, "reserved"):
            nv.plan(data, "1.3.0-beta.2", promote="v1.3.0-beta.2")

    def test_beta_promotion_requires_main(self):
        data = snapshot("Beta", betas=["v1.3.0-beta.2"])
        with self.assertRaisesRegex(ValueError, "from main"):
            nv.plan(data, "1.3.0-beta.2", promote="v1.3.0-beta.2")


class PreflightTests(unittest.TestCase):
    def test_annotated_tags_compare_peeled_commits(self):
        output = f"{OTHER}\trefs/tags/v1.2.3\n{SHA}\trefs/tags/v1.2.3^{{}}"
        self.assertEqual(nv.tag_refs(output), {"v1.2.3": SHA})

    def test_remote_failure_does_not_fall_back_to_local_tags(self):
        with patch.object(nv, "command", side_effect=["main", f"https://github.com/{nv.REPOSITORY}.git", "", ValueError("remote unavailable")]):
            with self.assertRaisesRegex(ValueError, "remote unavailable"):
                nv.collect_snapshot("origin", nv.REPOSITORY, "main")

    def test_wrong_branch_stops_before_network(self):
        with patch.object(nv, "command", return_value="Beta") as cmd:
            with self.assertRaisesRegex(ValueError, "Actual branch"):
                nv.collect_snapshot("origin", nv.REPOSITORY, "main")
            self.assertEqual(cmd.call_count, 1)

    def test_all_release_pages_are_read(self):
        release = snapshot()["releases"][0]
        replies = ["main", f"https://github.com/{nv.REPOSITORY}.git", "", f"{SHA}\trefs/tags/v1.2.3", json.dumps([[], [release]])]
        with patch.object(nv, "command", side_effect=replies) as cmd:
            data = nv.collect_snapshot("origin", nv.REPOSITORY, "main")
        self.assertEqual(data["releases"], [release])
        self.assertIn("--paginate", cmd.call_args.args[0])
        self.assertIn("--slurp", cmd.call_args.args[0])

    def test_process_failure_is_not_success(self):
        failed = subprocess.CompletedProcess(["gh"], 1, "", "not authenticated")
        with patch.object(nv.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(ValueError, "not verified"):
                nv.command(["gh", "api"])

    def test_missing_cli_is_identified(self):
        with patch.object(nv.subprocess, "run", side_effect=FileNotFoundError()):
            with self.assertRaisesRegex(ValueError, "Required executable not found: gh"):
                nv.command(["gh", "api"])

    def test_offline_cli_is_read_only_and_marks_its_output(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "snapshot.json"
            original = json.dumps(snapshot("Beta", betas=["v1.3.0-beta.1"]))
            fixture.write_text(original, encoding="utf-8")
            out = io.StringIO()
            with patch.object(nv, "command", side_effect=AssertionError("No commands in offline mode")), contextlib.redirect_stdout(out):
                code = nv.main(["--branch", "Beta", "--current", "1.3.0-beta.1", "--bump", "patch", "--snapshot", str(fixture)])
            self.assertEqual(code, 0)
            result = json.loads(out.getvalue())
            self.assertEqual(result["tag"], "v1.3.0-beta.2")
            self.assertTrue(result["offline"])
            self.assertEqual(fixture.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()

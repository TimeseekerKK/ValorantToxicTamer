"""The optional comparison must distinguish regressions from incompatible runs."""
import unittest

from scripts.performance_baseline import compare


class BaselineComparisonTests(unittest.TestCase):
    def test_reports_regression_and_tolerates_small_runner_noise(self):
        baseline = {"environment": {"platform": "offscreen"},
                    "metrics": {"start.elapsed_ms": 100, "start.working_set_MiB": 40}}
        current = {"environment": baseline["environment"],
                   "metrics": {"start.elapsed_ms": 240, "start.working_set_MiB": 58}}
        self.assertEqual([item["metric"] for item in compare(baseline, current)], ["start.working_set_MiB"])

    def test_rejects_comparison_across_modes_or_metric_sets(self):
        baseline = {"environment": {"frozen": False}, "metrics": {"time.elapsed_ms": 10}}
        for current in ({"environment": {"frozen": True}, "metrics": baseline["metrics"]},
                        {"environment": baseline["environment"], "metrics": {"other.elapsed_ms": 10}}):
            with self.subTest(current=current), self.assertRaises(ValueError):
                compare(baseline, current)

"""Record repeated isolated probes, optionally compare a same-environment baseline."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT_KEYS = ("schema", "python", "qt", "platform", "mode", "frozen", "message_count", "font_family")


def compare(baseline, current):
    if baseline["environment"] != current["environment"]:
        raise ValueError("Baseline environment differs; record a new comparable baseline.")
    if baseline["metrics"].keys() != current["metrics"].keys():
        raise ValueError("Baseline metrics differ; record a new baseline.")
    regressions = []
    for name, value in current["metrics"].items():
        old = baseline["metrics"][name]
        # Runner noise must not turn tiny deltas into a failed build.
        limit = old * 1.5 + 100 if name.endswith("elapsed_ms") else old * 1.2 + 8
        if value > limit:
            regressions.append({"metric": name, "baseline": old, "current": value, "limit": round(limit, 3)})
    return regressions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/performance/report.json")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--executable", type=Path, help="Probe a freshly built EXE instead of source")
    args = parser.parse_args()
    if not 1 <= args.runs <= 10:
        parser.error("--runs must be between 1 and 10")
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    command = [str(args.executable.resolve())] if args.executable else [sys.executable, "-B", str(ROOT / "main.py")]
    runs = []
    with tempfile.TemporaryDirectory(prefix="samples-", dir=args.output.parent) as directory:
        for index in range(args.runs):
            sample = Path(directory) / f"run-{index}.json"
            subprocess.run([*command, "--performance-check", str(sample)], cwd=ROOT,
                           env=environment, check=True, timeout=180,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            result = json.loads(sample.read_text(encoding="utf-8"))
            if not result["passed"]:
                raise RuntimeError("Performance probe failed")
            runs.append(result)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.strip())
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "commit": commit, "dirty": dirty,
              "version": runs[0]["version"],
              "environment": {**{key: runs[0][key] for key in ENVIRONMENT_KEYS},
                              "os": platform.platform(), "machine": platform.machine()},
              "metrics": {key: round(statistics.median(run["metrics"][key] for run in runs), 3)
                          for key in runs[0]["metrics"]}, "runs": runs}
    report["regressions"] = compare(json.loads(args.baseline.read_text(encoding="utf-8")), report) if args.baseline else []
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Performance report ({len(runs)} runs, median): {args.output}")
    for name, value in report["metrics"].items():
        print(f"  {name}: {value}")
    return 1 if report["regressions"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

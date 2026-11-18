"""Compare reference and candidate on one runner with an identical probe."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.performance_baseline import compare


def run(command, *, cwd=ROOT, **kwargs):
    return subprocess.run(command, cwd=cwd, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/performance/comparison.json")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.runs <= 10:
        parser.error("--runs must be between 1 and 10")
    # Resolve a commit before passing it to git archive; never accept options.
    commit = run(["git", "rev-parse", "--verify", f"{args.baseline_ref}^{{commit}}"],
                 capture_output=True, text=True).stdout.strip()
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    reference_report = args.output.with_name(args.output.stem + "-reference.json")
    candidate_report = args.output.with_name(args.output.stem + "-candidate.json")
    with tempfile.TemporaryDirectory(prefix="vtt-perf-") as directory:
        import tarfile
        root = Path(directory)
        archive = root / "source.tar"
        run(["git", "archive", "--format=tar", f"--output={archive}", commit])
        reference = root / "reference"
        reference.mkdir()
        with tarfile.open(archive) as source:
            source.extractall(reference, filter="data")
        # Only the measurement harness is shared. Runtime code comes entirely
        # from the chosen reference commit, with no checkout or branch changes.
        probe = reference / "valorant_toxic_tamer/performance_check.py"
        probe.write_bytes((ROOT / "valorant_toxic_tamer/performance_check.py").read_bytes())
        def measure(cwd, output):
            samples = []
            for index in range(args.runs):
                sample = root / f"{output.stem}-{index}.json"
                run([sys.executable, "-B", str(cwd / "main.py"), "--performance-check", str(sample)],
                    cwd=cwd, env=environment, timeout=180,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                value = json.loads(sample.read_text(encoding="utf-8"))
                if not value["passed"]:
                    raise RuntimeError("Performance probe failed")
                samples.append(value)
            from scripts.performance_baseline import ENVIRONMENT_KEYS
            import statistics
            result = {"environment": {key: samples[0][key] for key in ENVIRONMENT_KEYS},
                "metrics": {key: round(statistics.median(sample["metrics"][key] for sample in samples), 3)
                            for key in samples[0]["metrics"]}, "runs": samples}
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        baseline = measure(reference, reference_report)
        candidate = measure(ROOT, candidate_report)
    regressions = compare(baseline, candidate)
    report = {"reference_commit": commit, "candidate_commit": run(["git", "rev-parse", "HEAD"],
        capture_output=True, text=True).stdout.strip(), "baseline": baseline["metrics"],
        "candidate": candidate["metrics"], "regressions": regressions}
    report["candidate_dirty"] = bool(run(["git", "status", "--porcelain"],
        capture_output=True, text=True).stdout.strip())
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())

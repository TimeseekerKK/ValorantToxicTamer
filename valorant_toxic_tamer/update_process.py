"""Run update lookups in an expendable process, without loading TLS in the GUI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .update_protocol import Release


def worker_command(channel, result_path):
    arguments = ["--check-update-worker", channel, str(result_path)]
    if getattr(sys, "frozen", False):
        return [sys.executable, *arguments]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py"), *arguments]


def check_for_update(*, channel, cancel, timeout=120):
    if cancel.is_set():
        raise ValueError("检查更新已取消。")
    with tempfile.TemporaryDirectory(prefix="vtt-check-") as directory:
        result_path = Path(directory) / "result.json"
        environment = dict(os.environ)
        # This worker exits before the GUI, so it can reuse the one-file bundle.
        environment.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
        process = subprocess.Popen(worker_command(channel, result_path),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, env=environment,
                                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        try:
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if cancel.wait(0.05):
                    raise ValueError("检查更新已取消。")
                if time.monotonic() >= deadline:
                    raise ValueError("检查更新超时，请重试。")
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                if result["error"]:
                    raise ValueError(result["error"])
                if process.returncode != 0:
                    raise ValueError("检查更新进程异常退出，请重试。")
                release = result["release"]
                return Release(**release) if release is not None else None
            except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("检查更新进程未返回有效结果，请重试。") from exc
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            else:
                process.wait()


def check_worker(channel, result_path):
    from dataclasses import asdict

    try:
        from .updater import latest_release
        release = latest_release(channel=channel)
        result = {"release": asdict(release) if release is not None else None, "error": None}
        status = 0
    except Exception as exc:
        result = {"release": None, "error": str(exc)}
        status = 1
    Path(result_path).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return status

"""Run update lookups in an expendable process, without loading TLS in the GUI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .update_protocol import Release
from .config_manager import atomic_json


def _stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    else:
        process.wait()


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
            _stop_process(process)


def download_worker_command(manifest):
    arguments = ["--download-update-worker", str(manifest)]
    if getattr(sys, "frozen", False):
        return [sys.executable, *arguments]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py"), *arguments]


def download_update(release, target, cancel, *, progress=lambda received, total: None, timeout=630):
    """Own the staging path so terminating a blocked download leaves no partial EXE."""
    from dataclasses import asdict

    if cancel.is_set():
        raise ValueError("更新已取消。")
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".vtt-update-",
                                     suffix=".exe", delete=False) as stream:
        staged = Path(stream.name)
    completed = False
    try:
        with tempfile.TemporaryDirectory(prefix=".vtt-download-", dir=target.parent) as directory:
            root = Path(directory)
            manifest = root / "download.json"
            atomic_json(manifest, {"release": asdict(release), "target": str(target), "staged": str(staged)})
            environment = dict(os.environ)
            environment.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
            process = subprocess.Popen(download_worker_command(manifest),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=environment, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            last_progress = None

            def report_progress():
                nonlocal last_progress
                try:
                    payload = json.loads((root / "progress.json").read_text(encoding="utf-8"))
                    received, total = payload["received"], payload["total"]
                except (OSError, ValueError, KeyError, TypeError):
                    return
                if (type(received) is int and total == release.size and
                        0 <= received <= total and received != last_progress):
                    last_progress = received
                    progress(received, total)

            try:
                deadline = time.monotonic() + timeout
                while process.poll() is None:
                    if cancel.wait(0.05):
                        raise ValueError("更新已取消。")
                    if time.monotonic() >= deadline:
                        raise ValueError("更新下载超时，请重试。")
                    report_progress()
                if cancel.is_set():
                    raise ValueError("更新已取消。")
                report_progress()
                try:
                    result = json.loads((root / "result.json").read_text(encoding="utf-8"))
                    if result["error"]:
                        raise ValueError(result["error"])
                    if process.returncode != 0 or not staged.is_file():
                        raise ValueError("更新下载进程异常退出，请重试。")
                except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                    raise ValueError("更新下载进程未返回有效结果，请重试。") from exc
            finally:
                _stop_process(process)
        completed = True
        return staged
    finally:
        if not completed:
            staged.unlink(missing_ok=True)


def download_worker(manifest):
    """Run TLS and blocking reads only in the disposable download process."""
    import threading
    from .updater import download_release

    root = Path(manifest).parent
    last_report = 0.0

    def progress(received, total):
        nonlocal last_report
        now = time.monotonic()
        if received not in (0, total) and now - last_report < 0.1:
            return
        atomic_json(root / "progress.json", {"received": received, "total": total})
        last_report = now

    try:
        payload = json.loads(Path(manifest).read_text(encoding="utf-8"))
        download_release(Release(**payload["release"]), Path(payload["target"]), threading.Event(),
                         progress=progress, staged_path=Path(payload["staged"]))
        error = None
    except Exception as exc:
        error = str(exc)
    atomic_json(root / "result.json", {"error": error})
    return 1 if error else 0


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

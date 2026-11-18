"""Bound file reads to an owned process so even blocked paths can be cancelled."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .config_manager import atomic_json
from .message_manager import ImportPreview, prepare_txt_import
from .update_process import _stop_process


def worker_command(manifest):
    args = ["--import-worker", str(manifest)]
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py"), *args]


def prepare_import(path, existing=(), cancel=None, *, timeout=30):
    if cancel is not None and cancel.is_set():
        raise ValueError("导入已取消。")
    with tempfile.TemporaryDirectory(prefix="vtt-import-") as directory:
        root = Path(directory)
        manifest = root / "input.json"
        atomic_json(manifest, {"path": str(path), "existing": list(existing)})
        if cancel is not None and cancel.is_set():
            raise ValueError("导入已取消。")
        environment = dict(os.environ)
        environment.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
        process = subprocess.Popen(worker_command(manifest), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        try:
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if cancel is not None and cancel.wait(0.05):
                    raise ValueError("导入已取消。")
                if cancel is None:
                    time.sleep(0.05)
                if time.monotonic() >= deadline:
                    raise ValueError("读取导入文件超时，请将文件复制到本地后重试。")
            if cancel is not None and cancel.is_set():
                raise ValueError("导入已取消。")
            try:
                result = json.loads((root / "result.json").read_text(encoding="utf-8"))
                if result["error"]:
                    raise ValueError(result["error"])
                if process.returncode != 0:
                    raise ValueError("导入进程异常退出。")
                return ImportPreview(tuple(result["messages"]), tuple(result["unique_messages"]))
            except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("导入进程未返回有效结果，请重试。") from exc
        finally:
            _stop_process(process)


def import_worker(manifest):
    root = Path(manifest).parent
    try:
        payload = json.loads(Path(manifest).read_text(encoding="utf-8"))
        preview = prepare_txt_import(Path(payload["path"]), payload["existing"])
        result = {"messages": preview.messages, "unique_messages": preview.unique_messages, "error": None}
    except Exception as exc:
        result = {"error": str(exc)}
    atomic_json(root / "result.json", result)
    return 1 if result["error"] else 0

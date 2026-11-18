"""Preflight and conservative cleanup of marked, inactive update tasks."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

from .config_manager import atomic_json

DAY = 86400


def preflight_download(target, size):
    directory = Path(target).parent
    required = size + 16 * 1024 * 1024
    if shutil.disk_usage(directory).free < required:
        raise ValueError(f"安装目录所在磁盘空间不足，至少需要 {required / 2**20:.1f} MiB（含暂存余量）。")
    try:
        with tempfile.TemporaryFile(dir=directory) as stream:
            stream.write(b"vtt")
            stream.flush()
    except OSError as exc:
        raise OSError(f"安装目录无法写入，请检查权限或手动下载安装包：{directory}") from exc


def mark_task(directory, *, staged=None, helper_pid=None):
    atomic_json(Path(directory) / "owner.json", {"schema": 1, "pid": os.getpid(),
        "helper_pid": helper_pid, "staged": str(staged) if staged is not None else None})


def process_running(pid):
    # Failure to inspect a process is treated as active; never delete its files.
    if type(pid) is not int or pid <= 0:
        return True
    if sys.platform == "win32":
        import ctypes as C
        from ctypes import wintypes as W
        kernel = C.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        kernel.OpenProcess.restype = W.HANDLE
        kernel.GetExitCodeProcess.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
        kernel.GetExitCodeProcess.restype = W.BOOL
        kernel.CloseHandle.argtypes = [W.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return C.get_last_error() != 87  # ERROR_INVALID_PARAMETER: nonexistent PID.
        try:
            code = W.DWORD()
            return not kernel.GetExitCodeProcess(handle, C.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _is_link(path):
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def cleanup_update_files(install_directory, *, temp_directory=None, now=None):
    """Only remove known files in marked tasks after their owning processes exit.

    Download remnants expire after a day; success logs after 7 days and error
    logs after 30. Unmarked directories, links and unknown contents stay intact.
    """
    install = Path(install_directory).resolve()
    temporary = Path(temp_directory or tempfile.gettempdir()).resolve()
    now = time.time() if now is None else now
    for parent, pattern, download in ((install, ".vtt-download-*", True), (temporary, "vtt-updater-*", False)):
        try:
            directories = list(parent.glob(pattern))
        except OSError:
            continue
        for directory in directories:
            try:
                if _is_link(directory) or not directory.is_dir():
                    continue
                owner_path = directory / "owner.json"
                if _is_link(owner_path):
                    continue
                owner = json.loads(owner_path.read_text(encoding="utf-8"))
                if not isinstance(owner, dict) or owner.get("schema") != 1:
                    continue
                if process_running(owner.get("pid")) or (owner.get("helper_pid") is not None
                        and process_running(owner["helper_pid"])):
                    continue
                files = list(directory.iterdir())
                allowed = ({"owner.json", "download.json", "progress.json", "result.json"} if download else
                           {"owner.json", "update.json", "install.ps1", "ready", "proceed", "error.txt", "setup.log"})
                if any(path.name not in allowed or not path.is_file() or _is_link(path) for path in files):
                    continue
                age_limit = DAY if download else (30 if (directory / "error.txt").exists() else 7) * DAY
                if now - max(path.stat().st_mtime for path in files) < age_limit:
                    continue
                staged = owner.get("staged")
                if download and staged:
                    path = Path(staged)
                    if (path.parent.resolve() != install or not path.name.startswith(".vtt-update-")
                            or path.suffix != ".exe" or (path.exists() and _is_link(path))):
                        continue
                    path.unlink(missing_ok=True)
                # No recursive removal: unknown contents and concurrent changes
                # make rmdir fail safely, leaving the directory for inspection.
                for path in files:
                    path.unlink()
                directory.rmdir()
            except (OSError, ValueError, TypeError):
                continue

"""Static update lookup, verified staging and a detached Windows updater."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import truststore

from .app_version import VERSION
from .update_settings import CACHE_SECONDS, MANIFEST_URL, REPOSITORY, UPDATE_CHANNELS
from .update_manifest import validate_manifest
from .config_manager import atomic_json
from .update_protocol import Release, installed_executable, version_tuple
from .update_files import preflight_download, mark_task


EXE_NAME = "ValorantToxicTamer.exe"


def _open_update_url(request):
    # Use Windows chain building, including intermediate certificate retrieval,
    # for both the manifest request and redirected release downloads.
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        return urlopen(request, timeout=20, context=context)
    except (URLError, ssl.SSLCertVerificationError) as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        if isinstance(reason, ssl.SSLCertVerificationError):
            raise ValueError(
                "HTTPS 证书校验失败，无法安全连接更新服务器。\n"
                "请检查 Windows 日期和时间、系统证书更新，以及代理或安全软件的 HTTPS 证书设置。\n"
                "修复后请重新检查更新。"
            ) from exc
        raise


def _manifest_json(cache_path=None):
    if cache_path is not None:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            age = time.time() - cached["fetched_at"]
            if cached["source"] == MANIFEST_URL and 0 <= age < CACHE_SECONDS:
                validate_manifest(cached["manifest"])
                return cached["manifest"]
        except (OSError, ValueError, TypeError, KeyError):
            pass
    request = Request(MANIFEST_URL, headers={
        "Accept": "application/json", "User-Agent": f"ValorantToxicTamer/{VERSION}",
    })
    # Retry transient connection failures once; certificate and HTTP errors do not retry.
    for attempt in range(2):
        try:
            with _open_update_url(request) as response:
                raw = response.read(65537)
            break
        except HTTPError as exc:
            raise ValueError(
                f"暂时无法获取更新清单（HTTP {exc.code}），请稍后重试或打开下载页手动更新。"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            if attempt:
                raise ValueError("暂时无法连接更新服务，请重试或打开下载页手动更新。") from exc
            time.sleep(0.5)
    if len(raw) > 65536:
        raise ValueError("更新清单过大，已停止检查。请打开下载页手动更新。")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("更新清单不是有效的 JSON，请稍后重试或打开下载页手动更新。") from exc
    validate_manifest(payload)
    if cache_path is not None:
        try:
            atomic_json(cache_path, {"source": MANIFEST_URL, "fetched_at": time.time(), "manifest": payload})
        except OSError:
            # Read-only installation directories must still be able to check updates.
            pass
    return payload


def latest_release(current=VERSION, *, channel="stable", cache_path=None):
    if channel not in UPDATE_CHANNELS:
        raise ValueError("无法识别更新渠道。")
    current_version = version_tuple(current)
    releases = validate_manifest(_manifest_json(cache_path))
    candidates = [releases["stable"]]
    if channel == "beta" and "beta" in releases:
        candidates.append(releases["beta"])
    release = max(candidates, key=lambda item: version_tuple(item.version))
    target_version = version_tuple(release.version)
    rollback_to_stable = channel == "stable" and current_version[3] == 0
    if target_version == current_version or (target_version < current_version and not rollback_to_stable):
        return None
    return release


def download_release(release, target, cancel, *, progress=lambda received, total: None, staged_path=None,
                     phase=lambda stage: None):
    """Stage beside the installed EXE so replacement stays on the same volume."""
    staged = None
    try:
        if cancel.is_set():
            raise ValueError("更新已取消。")
        if staged_path is None:
            preflight_download(target, release.size)
        stream = (Path(staged_path).open("wb") if staged_path is not None else
                  tempfile.NamedTemporaryFile(dir=target.parent, prefix=".vtt-update-",
                                              suffix=".exe", delete=False))
        with stream:
            staged = Path(stream.name)
            request = Request(release.url, headers={"User-Agent": f"ValorantToxicTamer/{VERSION}"})
            deadline = time.monotonic() + 600
            for attempt in range(3):
                if cancel.is_set():
                    raise ValueError("更新已取消。")
                stream.seek(0)
                stream.truncate()
                digest = hashlib.sha256()
                received = 0
                phase("download")
                progress(0, release.size)
                try:
                    with _open_update_url(request) as response:
                        while True:
                            if cancel.is_set():
                                raise ValueError("更新已取消。")
                            if time.monotonic() > deadline:
                                raise ValueError("更新下载超时，请重试。")
                            chunk = response.read(256 * 1024)
                            if not chunk:
                                break
                            received += len(chunk)
                            if received > release.size:
                                raise ValueError("更新文件大小不符，请重试。")
                            stream.write(chunk)
                            digest.update(chunk)
                            progress(received, release.size)
                    if received != release.size:
                        raise IncompleteRead(b"", release.size - received)
                    break
                except (HTTPError, URLError, TimeoutError, ConnectionError, IncompleteRead) as exc:
                    if isinstance(exc, HTTPError) and exc.code not in (408, 429, 500, 502, 503, 504):
                        raise
                    if attempt == 2:
                        if isinstance(exc, IncompleteRead):
                            raise ValueError("更新文件下载不完整，请重试。") from exc
                        raise
                    phase("retry")
                    if cancel.wait(0.5 * (attempt + 1)):
                        raise ValueError("更新已取消。")
                    if time.monotonic() > deadline:
                        raise ValueError("更新下载超时，请重试。")
            phase("verify")
            stream.flush()
            os.fsync(stream.fileno())
        if received != release.size:
            raise ValueError("更新文件下载不完整，请重试。")
        if cancel.is_set():
            raise ValueError("更新已取消。")
        if release.digest and digest.hexdigest() != release.digest.split(":", 1)[1].lower():
            raise ValueError("更新文件 SHA-256 校验失败，请重试。")
        with staged.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ValueError("下载内容不是 Windows EXE 文件。")
        return staged
    except BaseException:
        if staged:
            staged.unlink(missing_ok=True)
        raise


def launch_installer(staged, target):
    """Copy the helper out of PyInstaller's temporary directory before exiting."""
    directory = Path(tempfile.mkdtemp(prefix="vtt-updater-"))
    process = None
    try:
        script = directory / "install.ps1"
        shutil.copyfile(Path(__file__).with_name("update_install.ps1"), script)
        manifest = directory / "update.json"
        with staged.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        manifest.write_text(json.dumps({
            "target": str(target), "staged": str(staged), "pid": os.getpid(),
            "sha256": checksum,
        }, ensure_ascii=False), encoding="utf-8-sig")
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        # The helper and restarted EXE must outlive the one-file extraction.
        environment = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
        bundle = getattr(sys, "_MEIPASS", None)
        set_dll_directory = None
        if bundle and sys.platform == "win32":
            import ctypes
            set_dll_directory = ctypes.WinDLL("kernel32", use_last_error=True).SetDllDirectoryW
            set_dll_directory.argtypes = [ctypes.c_wchar_p]
            set_dll_directory.restype = ctypes.c_int
            environment["PATH"] = os.pathsep.join(
                entry for entry in environment.get("PATH", "").split(os.pathsep)
                if entry and not Path(entry.strip('"')).resolve().is_relative_to(Path(bundle).resolve()))
            if not set_dll_directory(None):
                raise ctypes.WinError(ctypes.get_last_error())
        try:
            process = subprocess.Popen([
                str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-WindowStyle", "Hidden", "-File", str(script), "-Manifest", str(manifest),
            ], creationflags=subprocess.CREATE_NO_WINDOW,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                cwd=directory, env=environment)
            mark_task(directory, staged=staged, helper_pid=process.pid)
        finally:
            if set_dll_directory:
                set_dll_directory(str(bundle))
        deadline = time.monotonic() + 15
        while not (directory / "ready").exists():
            if (directory / "error.txt").exists():
                raise OSError((directory / "error.txt").read_text(encoding="utf-8-sig"))
            if process.poll() is not None:
                error_log = directory / "error.txt"
                _, stderr = process.communicate()
                detail = (error_log.read_text(encoding="utf-8-sig") if error_log.exists()
                          else stderr.decode("utf-8", errors="replace").strip() or "PowerShell 提前退出。")
                raise OSError(f"无法启动更新程序：{detail}")
            if time.monotonic() > deadline:
                raise OSError(f"无法启动更新程序，请检查 PowerShell。日志：{directory / 'error.txt'}")
            time.sleep(0.05)
        # The helper may now proceed even if Qt shutdown gets stuck.
        process.stderr.close()
        (directory / "proceed").touch()
        threading.Thread(target=process.wait, name="update-installer", daemon=True).start()
        return process
    except BaseException:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        if process and process.stderr:
            process.stderr.close()
        shutil.rmtree(directory, ignore_errors=True)
        raise

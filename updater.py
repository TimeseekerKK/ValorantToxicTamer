"""GitHub Release lookup, verified staging and a detached Windows updater."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from app_version import VERSION


REPOSITORY = "TimeseekerKK/ValorantToxicTamer"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
EXE_NAME = "ValorantToxicTamer.exe"


def version_tuple(value):
    match = re.fullmatch(r"[vV]?(\d+)\.(\d+)(?:\.(\d+))?", value)
    if not match:
        raise ValueError(f"无法识别版本号：{value}（应为 v1.2.3 格式）")
    return tuple(int(part or 0) for part in match.groups())


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    size: int
    digest: str | None


def latest_release(current=VERSION):
    request = Request(LATEST_URL, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"ValorantToxicTamer/{VERSION}",
    })
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            raise ValueError("仓库尚无可用的正式 Release。") from exc
        if exc.code in (403, 429):
            raise ValueError("GitHub 请求受限，请稍后重试。") from exc
        raise
    if not isinstance(payload, dict):
        raise ValueError("GitHub 返回了无效的版本信息。")
    tag = payload.get("tag_name", "")
    if payload.get("draft") or payload.get("prerelease"):
        raise ValueError("最新版本不是正式 Release。")
    if version_tuple(tag) <= version_tuple(current):
        return None
    assets = [asset for asset in payload.get("assets", [])
              if asset.get("state") == "uploaded" and asset.get("name", "").lower().endswith(".exe")]
    exact = [asset for asset in assets if asset["name"].casefold() == EXE_NAME.casefold()]
    if len(exact) == 1:
        asset = exact[0]
    elif len(assets) == 1:
        asset = assets[0]
    else:
        raise ValueError(f"最新 Release 未提供唯一的程序 EXE，请上传 {EXE_NAME}。")
    url = asset.get("browser_download_url", "")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "github.com"
            or not parsed.path.startswith(f"/{REPOSITORY}/releases/download/")):
        raise ValueError("更新文件地址不属于本项目的 GitHub Release。")
    size = asset.get("size")
    if type(size) is not int or size <= 0:
        raise ValueError("更新文件大小无效。")
    digest = asset.get("digest")
    if digest is not None and not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise ValueError("GitHub 返回了不支持的文件校验信息。")
    return Release(tag, url, size, digest)


def installed_executable():
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise ValueError("覆盖更新仅支持打包后的 Windows EXE，请使用发布版程序。")
    return Path(sys.executable).resolve()


def download_release(release, target, cancel):
    """Stage beside the installed EXE so replacement stays on the same volume."""
    staged = None
    try:
        if cancel.is_set():
            raise ValueError("更新已取消。")
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".vtt-update-",
                                         suffix=".exe", delete=False) as stream:
            staged = Path(stream.name)
            request = Request(release.url, headers={"User-Agent": f"ValorantToxicTamer/{VERSION}"})
            digest = hashlib.sha256()
            received = 0
            deadline = time.monotonic() + 600
            with urlopen(request, timeout=20) as response:
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
            stream.flush()
            os.fsync(stream.fileno())
        if received != release.size:
            raise ValueError("更新文件下载不完整，请重试。")
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

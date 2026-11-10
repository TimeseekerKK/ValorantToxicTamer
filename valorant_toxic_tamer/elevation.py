"""Request administrator access before starting the desktop application."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys


def ensure_administrator():
    """Return None to continue here, or an exit code after an elevation attempt."""
    if sys.platform != "win32":
        return None
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    is_admin = shell32.IsUserAnAdmin
    is_admin.argtypes = []
    is_admin.restype = ctypes.c_int
    if is_admin():
        return None

    arguments = sys.argv[1:]
    frozen = getattr(sys, "frozen", False)
    if not frozen:
        arguments = [str(Path(__file__).resolve().parents[1] / "main.py"), *arguments]
    execute = shell32.ShellExecuteW
    execute.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                        ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
    execute.restype = ctypes.c_void_p
    # The elevated one-file process must unpack its own bundle: this process
    # exits after handing off and its temporary directory will be removed.
    previous = os.environ.get("PYINSTALLER_RESET_ENVIRONMENT")
    try:
        if frozen:
            os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        result = execute(None, "runas", sys.executable,
                         subprocess.list2cmdline(arguments), os.getcwd(), 1)
    finally:
        if frozen:
            if previous is None:
                os.environ.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
            else:
                os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = previous
    if result and result > 32:
        return 0
    # A declined UAC prompt must not fall through into an unelevated UI.
    ctypes.windll.user32.MessageBoxW(
        None, "未获得管理员权限，程序已退出。请重新启动并允许管理员权限请求。",
        "无法启动", 0x10)
    return 1

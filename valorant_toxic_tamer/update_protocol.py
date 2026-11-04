"""Small update values shared by the GUI and the network worker."""
from dataclasses import dataclass
from pathlib import Path
import re
import sys


def version_tuple(value):
    match = re.fullmatch(r"[vV]?(\d+)\.(\d+)(?:\.(\d+))?(?:(-beta)(?:\.([1-9]\d*))?)?", value)
    if not match:
        raise ValueError(f"无法识别版本号：{value}（应为 v1.2.3 或 v1.2.3-beta.1 格式）")
    major, minor, patch, beta, number = match.groups()
    return (int(major), int(minor), int(patch or 0), int(beta is None), int(number or 0))


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    size: int
    digest: str | None


def installed_executable():
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise ValueError("覆盖更新仅支持打包后的 Windows EXE，请使用发布版程序。")
    return Path(sys.executable).resolve()

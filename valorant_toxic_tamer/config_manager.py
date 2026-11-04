"""Validated, atomic local storage. Invalid files are never overwritten."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

DEFAULT_CONFIG = {
    "team_hotkey": "F8",
    "all_hotkey": "F9",
    "cooldown": 0.5,
    "start_hidden": True,
    "autostart": False,
    "font_size": 11,
}
HOTKEYS = tuple(f"F{i}" for i in range(1, 12))  # F12 is reserved by Windows.
FONT_SIZES = tuple(range(9, 17))


def data_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(os.environ["LOCALAPPDATA"]) / "ValorantToxicTamer" / "data"
    return Path(__file__).resolve().parents[1] / "data"


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".tmp", delete=False) as stream:
            name = stream.name
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def load_json(path: Path, default, validate):
    try:
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            validate(value)
            return value
        validate(default)
        atomic_json(path, default)
        return default.copy()
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"无法读取 {path}\n{exc}\n原文件未被覆盖，请备份后修复文件。") from exc


def validate_config(value):
    if not isinstance(value, dict) or set(value) not in (
            set(DEFAULT_CONFIG), set(DEFAULT_CONFIG) - {"font_size"}):
        raise ValueError("配置字段不完整或含未知字段")
    font_size = value.get("font_size", DEFAULT_CONFIG["font_size"])
    if type(font_size) is not int or font_size not in FONT_SIZES:
        raise ValueError("字体大小须为 9–16 pt 的整数")
    if any(value[k] not in HOTKEYS for k in ("team_hotkey", "all_hotkey")):
        raise ValueError("快捷键须为 F1–F11")
    if value["team_hotkey"] == value["all_hotkey"]:
        raise ValueError("两个频道不能使用同一个快捷键")
    seconds = value["cooldown"]
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0.2 <= seconds <= 2:
        raise ValueError("冷却时间须在 0.2–2 秒之间")
    if any(type(value[k]) is not bool for k in ("start_hidden", "autostart")):
        raise ValueError("启动设置必须为布尔值")


class ConfigManager:
    def __init__(self, path: Path):
        self.path = path
        self.value = load_json(path, DEFAULT_CONFIG, validate_config)
        # Keep valid old files intact until the user explicitly saves settings.
        self.value.setdefault("font_size", DEFAULT_CONFIG["font_size"])

    def save(self, value):
        validate_config(value)
        value = {**DEFAULT_CONFIG, **value}
        atomic_json(self.path, value)
        self.value = value.copy()


def set_autostart(enabled: bool):
    """Only called on an explicit settings change; never on normal startup."""
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            executable = Path(sys.executable)
            args = [str(executable)]
            if not getattr(sys, "frozen", False):
                windowless = executable.with_name("pythonw.exe")
                args = [str(windowless if windowless.exists() else executable),
                        str(Path(__file__).resolve().parents[1] / "main.py")]
            winreg.SetValueEx(key, "ValorantToxicTamer", 0, winreg.REG_SZ,
                             subprocess.list2cmdline(args))
        else:
            try:
                winreg.DeleteValue(key, "ValorantToxicTamer")
            except FileNotFoundError:
                pass

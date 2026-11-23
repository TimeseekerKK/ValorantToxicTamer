"""Local presets kept compatible with versions that only read config.json."""
from .config_manager import atomic_json, load_json
from .message_manager import ALL_CATEGORY


WHEEL_LIMIT = 6


def validate_wheel_settings(value):
    if (not isinstance(value, dict) or set(value) != {"enabled", "categories"}
            or type(value["enabled"]) is not bool or not isinstance(value["categories"], list)):
        raise ValueError("类别轮盘设置格式无效。")
    ids = value["categories"]
    if (len(ids) > WHEEL_LIMIT
            or any(not isinstance(cid, str) or not cid or cid == ALL_CATEGORY for cid in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError(f"请选择最多 {WHEEL_LIMIT} 个不同的类别。")
    if value["enabled"] and not ids:
        raise ValueError("启用轮盘前请至少选择一个类别。")


class WheelSettings:
    def __init__(self, path):
        self.path = path
        self.enabled = False
        self.categories = ()
        self.error = None
        if not path.exists():
            return
        try:
            value = load_json(path, {"enabled": False, "categories": []}, validate_wheel_settings)
        except ValueError as exc:
            self.error = str(exc)
        else:
            self.enabled = value["enabled"]
            self.categories = tuple(value["categories"])

    def save(self, enabled, categories):
        value = {"enabled": enabled, "categories": list(categories)}
        validate_wheel_settings(value)
        atomic_json(self.path, value)
        self.enabled = enabled
        self.categories = tuple(value["categories"])
        self.error = None

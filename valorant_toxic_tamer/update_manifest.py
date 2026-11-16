"""Validate the static update contract without importing networking or Qt."""
import re
from urllib.parse import urlsplit

from .update_protocol import Release, version_tuple
from .update_settings import REPOSITORY


def validate_manifest(payload):
    if (not isinstance(payload, dict) or type(payload.get("schema")) is not int
            or payload["schema"] != 1 or not isinstance(payload.get("channels"), dict)
            or set(payload["channels"]) != {"stable", "beta"}):
        raise ValueError("更新清单格式无效或版本不受支持。")
    releases = {}
    for channel, item in payload["channels"].items():
        if channel == "beta" and item is None:
            continue
        if not isinstance(item, dict) or set(item) != {"version", "url", "size", "digest"}:
            raise ValueError("更新清单的版本信息不完整。")
        tag = item["version"]
        if not isinstance(tag, str) or not re.fullmatch(r"v\d+\.\d+\.\d+(?:-beta(?:\.[1-9]\d*)?)?", tag):
            raise ValueError("更新清单的版本号无效。")
        version = version_tuple(tag)
        if (channel == "stable") != bool(version[3]):
            raise ValueError("更新清单的版本与渠道不匹配。")
        if not isinstance(item["url"], str):
            raise ValueError("更新文件地址无效。")
        parsed = urlsplit(item["url"])
        expected_path = f"/{REPOSITORY}/releases/download/{tag}/ValorantToxicTamer-Setup-{tag}.exe"
        if (parsed.scheme != "https" or parsed.netloc != "github.com"
                or parsed.path != expected_path or parsed.query or parsed.fragment):
            raise ValueError("更新文件地址不属于本项目的 GitHub Release 安装包。")
        if type(item["size"]) is not int or item["size"] <= 0:
            raise ValueError("更新文件大小无效。")
        if not isinstance(item["digest"], str) or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", item["digest"]):
            raise ValueError("更新清单缺少有效的 SHA-256 校验信息。")
        releases[channel] = Release(**item)
    return releases

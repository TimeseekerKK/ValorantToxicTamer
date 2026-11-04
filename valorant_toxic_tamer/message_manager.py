from pathlib import Path
import unicodedata

from .config_manager import atomic_json, load_json


def validate_messages(messages):
    if not isinstance(messages, list):
        raise ValueError("消息文件必须是字符串列表")
    for message in messages:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("消息不能为空")
        if any(unicodedata.category(c) in ("Cc", "Cs", "Zl", "Zp") for c in message):
            raise ValueError("每条消息只能占一行，不能包含换行、制表符或控制字符")


class MessageManager:
    def __init__(self, path: Path):
        self.path = path
        self.messages = load_json(path, [], validate_messages)
        self.index = 0

    @property
    def current(self):
        return self.messages[self.index] if self.messages else None

    def advance(self):
        if self.messages:
            self.index = (self.index + 1) % len(self.messages)

    def replace(self, messages):
        validate_messages(messages)
        atomic_json(self.path, messages)
        self.messages = list(messages)
        self.index = 0

    def import_txt(self, path: Path):
        # UTF-8 (including BOM) preferred; GB18030 accommodates Windows Chinese TXT.
        raw = path.read_bytes()
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = raw.decode("gb18030")
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            raise ValueError("TXT 文件中没有非空消息")
        self.replace(self.messages + lines)

    def export_txt(self, path: Path):
        path.write_text("\n".join(self.messages) + ("\n" if self.messages else ""), encoding="utf-8-sig")

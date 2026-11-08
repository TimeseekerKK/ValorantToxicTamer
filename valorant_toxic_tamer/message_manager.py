from pathlib import Path
from dataclasses import dataclass
import unicodedata

from .config_manager import atomic_json, load_json

MAX_IMPORT_BYTES = 8 * 1024 * 1024
MAX_IMPORT_LINES = 20000


@dataclass(frozen=True)
class ImportPreview:
    messages: tuple[str, ...]
    unique_messages: tuple[str, ...]

    @property
    def duplicate_count(self):
        return len(self.messages) - len(self.unique_messages)


def prepare_txt_import(path: Path, existing=()) -> ImportPreview:
    """Read and validate without touching application data; safe in a worker."""
    with path.open("rb") as stream:
        raw = stream.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValueError("TXT 文件不能超过 8 MiB，请拆分后导入。")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("gb18030")
    lines = tuple(line.strip() for line in content.splitlines() if line.strip())
    if not lines:
        raise ValueError("TXT 文件中没有非空消息")
    if len(lines) > MAX_IMPORT_LINES:
        raise ValueError("单次最多导入 20000 条消息，请拆分后导入。")
    validate_messages(list(lines))
    return ImportPreview(lines, deduplicate_messages(lines, existing))


def deduplicate_messages(messages, existing=()):
    seen = set(existing)
    unique = []
    for line in messages:
        if line not in seen:
            unique.append(line)
            seen.add(line)
    return tuple(unique)


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
        preview = prepare_txt_import(path, self.messages)
        self.replace(self.messages + list(preview.messages))

    def export_txt(self, path: Path):
        path.write_text("\n".join(self.messages) + ("\n" if self.messages else ""), encoding="utf-8-sig")

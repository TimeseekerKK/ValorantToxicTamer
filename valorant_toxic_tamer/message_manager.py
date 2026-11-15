from pathlib import Path
from dataclasses import dataclass
from copy import deepcopy
import os
import unicodedata
from uuid import uuid4

from .config_manager import atomic_json, load_json

MAX_IMPORT_BYTES = 8 * 1024 * 1024
MAX_IMPORT_LINES = 20000
ALL_CATEGORY = "all"
UNCATEGORIZED = "uncategorized"
CATEGORY_MODES = {"sequential": "逐类循环", "alternating": "交替循环"}


def validate_category_name(name):
    if (not isinstance(name, str) or not name.strip() or name != name.strip()
            or len(name) > 40 or any(unicodedata.category(c).startswith("C") for c in name)):
        raise ValueError("类别名称须为 1–40 个字符，不能包含控制字符或首尾空格")


def empty_library():
    return {"version": 2, "categories": [{"id": UNCATEGORIZED, "name": "未分类"}],
            "messages": [], "selected_categories": [ALL_CATEGORY]}


def validate_library(value):
    if isinstance(value, list):
        validate_messages(value)
        return
    if (not isinstance(value, dict) or set(value) != {
            "version", "categories", "messages", "selected_categories"}
            or type(value["version"]) is not int or value["version"] != 2):
        raise ValueError("消息库格式或版本不受支持")
    if not isinstance(value["categories"], list) or not isinstance(value["messages"], list):
        raise ValueError("类别和消息必须是列表")
    ids, names = set(), {"全部消息"}
    for category in value["categories"]:
        if not isinstance(category, dict) or set(category) != {"id", "name"}:
            raise ValueError("类别格式不正确")
        cid, name = category["id"], category["name"]
        validate_category_name(name)
        if not isinstance(cid, str) or not cid or cid == ALL_CATEGORY or cid in ids or name.casefold() in names:
            raise ValueError("类别标识或名称重复")
        if (cid == UNCATEGORIZED) != (name == "未分类"):
            raise ValueError("不能修改内置的未分类类别")
        ids.add(cid)
        names.add(name.casefold())
    if UNCATEGORIZED not in ids:
        raise ValueError("缺少未分类类别")
    for message in value["messages"]:
        if not isinstance(message, dict) or set(message) != {"text", "category"}:
            raise ValueError("消息格式不正确")
        if not isinstance(message["category"], str) or message["category"] not in ids:
            raise ValueError("消息所属类别不存在")
        validate_messages([message["text"]])
    selected = value["selected_categories"]
    if (not isinstance(selected, list) or any(not isinstance(cid, str) for cid in selected)
            or len(selected) != len(set(selected))
            or any(cid not in ids | {ALL_CATEGORY} for cid in selected)
            or (ALL_CATEGORY in selected and len(selected) != 1)):
        raise ValueError("发送类别无效；全部消息不能与其他类别同时选择")


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
        value = load_json(path, empty_library(), validate_library)
        self._legacy = isinstance(value, list)
        if self._legacy:
            library = empty_library()
            library["messages"] = [self._entry(text, UNCATEGORIZED) for text in value]
            value = library
        self._library = value
        self.mode = "sequential"
        self._positions = {}
        self._active_category = None
        self._rebuild()

    @staticmethod
    def _entry(text, category):
        return {"text": text, "category": category}

    def _rebuild(self):
        self._messages = [m["text"] for m in self._library["messages"]]
        self._rows = {c["id"]: [] for c in self.categories}
        self._rows[ALL_CATEGORY] = list(range(len(self._messages)))
        for row, entry in enumerate(self._library["messages"]):
            self._rows[entry["category"]].append(row)
        self._positions = {cid: self._positions.get(cid, 0) % max(1, len(rows))
                           for cid, rows in self._rows.items()}

    @property
    def messages(self):
        return self._messages.copy()

    @property
    def categories(self):
        return deepcopy(self._library["categories"])

    @property
    def selected_categories(self):
        return self._library["selected_categories"].copy()

    def category_name(self, cid):
        if cid == ALL_CATEGORY:
            return "全部消息"
        return next(c["name"] for c in self.categories if c["id"] == cid)

    def rows_for(self, cid):
        if cid not in self._rows:
            raise ValueError("类别不存在")
        return self._rows[cid].copy()

    def category_for(self, row):
        return self._library["messages"][row]["category"]

    @property
    def current_category(self):
        candidates = [cid for cid in self.selected_categories if self._rows[cid]]
        return (self._active_category if self._active_category in candidates
                else candidates[0] if candidates else None)

    @property
    def position(self):
        cid = self.current_category
        return self._positions[cid] if cid else 0

    @property
    def current_count(self):
        cid = self.current_category
        return len(self._rows[cid]) if cid else 0

    @property
    def current_row(self):
        cid = self.current_category
        return self._rows[cid][self._positions[cid]] if cid else None

    @property
    def index(self):
        row = self.current_row
        return row if row is not None else 0

    @index.setter
    def index(self, row):
        cid = self.current_category
        if cid and row in self._rows[cid]:
            self._positions[cid] = self._rows[cid].index(row)

    @property
    def current(self):
        row = self.current_row
        return self._messages[row] if row is not None else None

    def advance(self):
        cid = self.current_category
        if cid is None:
            return
        self._positions[cid] = (self._positions[cid] + 1) % len(self._rows[cid])
        candidates = [c for c in self.selected_categories if self._rows[c]]
        if self.mode == "alternating" or self._positions[cid] == 0:
            self._active_category = candidates[(candidates.index(cid) + 1) % len(candidates)]
        else:
            self._active_category = cid

    def set_mode(self, mode):
        if mode not in CATEGORY_MODES:
            raise ValueError("多类别发送方式无效")
        if mode != self.mode:
            self.mode = mode
            self._active_category = None

    def _commit(self, library, reset=(), *, selection_changed=False):
        # An unchanged library must not migrate legacy data or reset progress.
        if library == self._library:
            return False
        validate_library(library)
        if self._legacy:
            # Keep the exact old file before the first successful format migration.
            backup = self.path.with_name(f"{self.path.stem}.legacy-{uuid4().hex}.json")
            try:
                with backup.open("xb") as stream:
                    stream.write(self.path.read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError:
                backup.unlink(missing_ok=True)
                raise
        atomic_json(self.path, library)
        self._legacy = False
        self._library = library
        for cid in reset:
            self._positions[cid] = 0
        if selection_changed:
            self._active_category = None
        self._rebuild()
        return True

    def select_categories(self, categories):
        library = deepcopy(self._library)
        library["selected_categories"] = list(categories)
        return self._commit(library, selection_changed=True)

    def create_category(self, name):
        cid = uuid4().hex
        library = deepcopy(self._library)
        library["categories"].append({"id": cid, "name": name.strip()})
        self._commit(library)
        return cid

    def rename_category(self, cid, name):
        if cid in (ALL_CATEGORY, UNCATEGORIZED) or cid not in self._rows:
            raise ValueError("内置类别不能重命名")
        name = name.strip()
        if name == self.category_name(cid):
            return False
        library = deepcopy(self._library)
        next(c for c in library["categories"] if c["id"] == cid)["name"] = name
        return self._commit(library)

    def delete_category(self, cid):
        if cid in (ALL_CATEGORY, UNCATEGORIZED) or cid not in self._rows:
            raise ValueError("内置类别不能删除")
        library = deepcopy(self._library)
        library["categories"] = [c for c in library["categories"] if c["id"] != cid]
        for entry in library["messages"]:
            if entry["category"] == cid:
                entry["category"] = UNCATEGORIZED
        library["selected_categories"] = [c for c in self.selected_categories if c != cid]
        return self._commit(library, (UNCATEGORIZED,), selection_changed=True)

    def _edit_entries(self, entries, affected):
        library = deepcopy(self._library)
        library["messages"] = entries
        return self._commit(library, set(affected) | {ALL_CATEGORY})

    def append(self, messages, category=UNCATEGORIZED):
        messages = list(messages)
        validate_messages(messages)
        if category == ALL_CATEGORY:
            category = UNCATEGORIZED
        return self._edit_entries(deepcopy(self._library["messages"]) + [self._entry(t, category) for t in messages],
                                  (category,))

    def edit_message(self, row, text):
        if self._messages[row] == text:
            return False
        entries = deepcopy(self._library["messages"])
        entries[row]["text"] = text
        return self._edit_entries(entries, (entries[row]["category"],))

    def delete_messages(self, rows):
        rows = set(rows)
        entries = self._library["messages"]
        return self._edit_entries([deepcopy(e) for i, e in enumerate(entries) if i not in rows],
                                  {e["category"] for i, e in enumerate(entries) if i in rows})

    def move_to_category(self, rows, category):
        if category == ALL_CATEGORY or category not in self._rows:
            raise ValueError("请选择一个实际类别")
        rows = [row for row in rows if self.category_for(row) != category]
        if not rows:
            return False
        entries = deepcopy(self._library["messages"])
        affected = {category}
        for row in rows:
            affected.add(entries[row]["category"])
            entries[row]["category"] = category
        return self._edit_entries(entries, affected)

    def swap(self, row, target):
        entries = deepcopy(self._library["messages"])
        affected = {entries[row]["category"], entries[target]["category"]}
        entries[row], entries[target] = entries[target], entries[row]
        return self._edit_entries(entries, affected)

    def replace(self, messages):
        validate_messages(messages)
        return self._edit_entries([self._entry(t, UNCATEGORIZED) for t in messages], self._rows)

    def import_txt(self, path: Path):
        preview = prepare_txt_import(path, self.messages)
        return self.append(preview.messages)

    def export_txt(self, path: Path, category=ALL_CATEGORY):
        messages = [self._messages[row] for row in self.rows_for(category)]
        path.write_text("\n".join(messages) + ("\n" if messages else ""), encoding="utf-8-sig")

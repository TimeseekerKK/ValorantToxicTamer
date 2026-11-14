"""Move personal data only after a complete, verified copy is committed."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile


def legacy_directory():
    return Path(os.environ["LOCALAPPDATA"]) / "ValorantToxicTamer" / "data"


def has_data(directory):
    return directory.is_dir() and any(p.name != "application.lock" for p in directory.iterdir())


def _snapshot(directory):
    result = {}
    for root, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs + files:
            path = Path(root) / name
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError(f"数据目录包含链接，未迁移：{path}")
        for name in files:
            path = Path(root) / name
            if path == directory / "application.lock":
                continue
            with path.open("rb") as stream:
                result[path.relative_to(directory)] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def migrate_data(source, target):
    """An existing target is never merged/overwritten; locked sources stay intact."""
    from PySide6.QtCore import QLockFile

    source, target = Path(source).absolute(), Path(target).absolute()
    if source.resolve() == target.resolve():
        return
    if not has_data(source):
        return
    if source.is_symlink() or getattr(source.lstat(), "st_file_attributes", 0) & 0x400:
        raise ValueError("旧数据目录是链接，未迁移。")
    if source.resolve() in target.resolve().parents or target.resolve() in source.resolve().parents:
        raise ValueError("新旧数据目录不能互相包含。")
    if target.exists() and (target.is_symlink() or any(target.iterdir())):
        raise ValueError("目标 data 已有数据，未覆盖，也未删除旧数据。")
    target.parent.mkdir(parents=True, exist_ok=True)
    locks = [QLockFile(str(source / "application.lock")),
             QLockFile(str(target.parent / ".vtt-data-migration.lock"))]
    acquired = []
    stage = None
    try:
        for lock in locks:
            lock.setStaleLockTime(0)
            if not lock.tryLock(0):
                raise ValueError("数据正在使用或无法锁定，请退出旧版程序后重试。")
            acquired.append(lock)
        before = _snapshot(source)
        stage = Path(tempfile.mkdtemp(prefix=".vtt-data-", dir=target.parent))
        shutil.copytree(source, stage, dirs_exist_ok=True,
                        ignore=lambda directory, names: ["application.lock"] if Path(directory) == source else [])
        if _snapshot(stage) != before or _snapshot(source) != before:
            raise ValueError("数据复制校验失败或源数据已变化，旧数据保留。")
        if target.exists():
            target.rmdir()  # Fails rather than replacing a concurrently created file.
        stage.rename(target)
        stage = None
        # Check the full source again before removing any committed source files.
        if _snapshot(source) != before:
            raise ValueError("新数据已保存，但旧数据发生变化，未删除旧数据。")
        for relative, expected in before.items():
            path = source / relative
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                    raise ValueError("新数据已保存，但旧数据发生变化，剩余旧文件保留。")
            path.unlink()
        for root, dirs, files in os.walk(source, topdown=False):
            if Path(root) != source:
                try:
                    Path(root).rmdir()
                except OSError:
                    pass
    finally:
        if stage is not None:
            shutil.rmtree(stage)
        for lock in reversed(acquired):
            lock.unlock()
    try:
        source.rmdir()
    except OSError:
        pass


def run(source, target):
    try:
        migrate_data(Path(source), Path(target))
        return 0
    except (OSError, ValueError) as exc:
        # Installer can show the concrete error without booting the desktop UI.
        Path(target).parent.joinpath("migration-error.txt").write_text(str(exc), encoding="utf-8-sig")
        return 1

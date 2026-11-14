"""Migration failure must never destroy the only copy of personal data."""
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QLockFile
from valorant_toxic_tamer.data_migration import migrate_data


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="迁移 test ", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).absolute()
        self.source = self.root / "old" / "data"
        self.target = self.root / "new" / "data"
        self.source.mkdir(parents=True)
        (self.source / "messages.json").write_bytes(b'\xef\xbb\xbf["hello"]')
        (self.source / "logs").mkdir()
        (self.source / "logs" / "old.log").write_bytes(b"log contents")

    def assert_source_intact(self):
        self.assertEqual((self.source / "messages.json").read_bytes(), b'\xef\xbb\xbf["hello"]')
        self.assertEqual((self.source / "logs" / "old.log").read_bytes(), b"log contents")

    def test_move_verifies_all_bytes_and_removes_old_files(self):
        migrate_data(self.source, self.target)
        self.assertFalse(self.source.exists())
        self.assertEqual((self.target / "messages.json").read_bytes(), b'\xef\xbb\xbf["hello"]')
        self.assertEqual((self.target / "logs" / "old.log").read_bytes(), b"log contents")
        self.assertFalse((self.target / "application.lock").exists())

    def test_existing_target_is_never_overwritten(self):
        self.target.mkdir(parents=True)
        (self.target / "messages.json").write_bytes(b"existing")
        with self.assertRaisesRegex(ValueError, "已有数据"):
            migrate_data(self.source, self.target)
        self.assert_source_intact()
        self.assertEqual((self.target / "messages.json").read_bytes(), b"existing")

    def test_busy_source_is_not_copied_or_deleted(self):
        lock = QLockFile(str(self.source / "application.lock"))
        self.assertTrue(lock.tryLock(0))
        try:
            with self.assertRaisesRegex(ValueError, "正在使用"):
                migrate_data(self.source, self.target)
            self.assert_source_intact()
            self.assertFalse(self.target.exists())
        finally:
            lock.unlock()

    def test_copy_failure_and_corrupt_copy_keep_source_and_clean_staging(self):
        original = shutil.copytree
        def corrupt(*args, **kwargs):
            result = original(*args, **kwargs)
            Path(args[1], "messages.json").write_bytes(b"truncated")
            return result
        for fault in (OSError("disk full"), corrupt):
            with patch("valorant_toxic_tamer.data_migration.shutil.copytree", side_effect=fault):
                with self.assertRaises((OSError, ValueError)):
                    migrate_data(self.source, self.target)
            self.assert_source_intact()
            self.assertFalse(self.target.exists())
            self.assertEqual(list(self.target.parent.iterdir()), [])

    def test_source_change_after_copy_is_not_deleted(self):
        original = shutil.copytree
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.source / "new.txt").write_bytes(b"new data")
            return result
        with patch("valorant_toxic_tamer.data_migration.shutil.copytree", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "变化"):
                migrate_data(self.source, self.target)
        self.assert_source_intact()
        self.assertEqual((self.source / "new.txt").read_bytes(), b"new data")

    def test_same_directory_is_noop_and_nested_target_rejected(self):
        migrate_data(self.source, self.source)
        with self.assertRaisesRegex(ValueError, "互相包含"):
            migrate_data(self.source, self.source / "nested")
        self.assert_source_intact()

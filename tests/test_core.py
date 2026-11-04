import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from config_manager import ConfigManager, DEFAULT_CONFIG, validate_config
from message_manager import MessageManager, validate_messages
from sender import Sender


class FakeAPI:
    def __init__(self):
        self.foreground = (100, 200)
        self.modified = False
        self.events = []
        self.batches = []
        self.fail_text = False

    def target(self):
        return self.foreground

    def is_foreground(self, target):
        return self.foreground == target

    def modifiers_down(self):
        return self.modified

    def key(self, vk, down):
        self.events.append((vk, down))

    def keys(self, virtual_keys, down):
        self.batches.append((tuple(virtual_keys), down))
        for vk in virtual_keys:
            self.key(vk, down)

    def text_character(self, value):
        if self.fail_text:
            raise OSError("模拟输入失败")
        self.events.append(value)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.messages = MessageManager(self.path / "messages.json")
        self.messages.replace(["你好", "B", "C"])
        self.api = FakeAPI()
        self.time = 10.0
        self.reports = []
        self.sender = Sender(self.messages, self.api, notify=self.reports.append,
                             clock=lambda: self.time, wait=lambda _: None)
        self.addCleanup(self.sender.stop)

    def send(self, channel):
        accepted = self.sender.trigger(channel)
        if self.sender.thread:
            self.sender.thread.join(2)
            self.assertFalse(self.sender.thread.is_alive())
        return accepted

    def test_team_keys_and_unicode(self):
        self.assertTrue(self.send("team"))
        self.assertEqual(self.api.events, [(13, True), (13, False), "你", "好", (13, True), (13, False)])
        self.assertEqual(self.messages.index, 1)

    def test_all_shift_released_before_text_and_final_enter(self):
        self.send("all")
        self.assertEqual(self.api.events, [(16, True), (13, True), (13, False), (16, False),
                                          "你", "好", (13, True), (13, False)])

    def test_all_chord_batches_keydown_without_gap_and_plain_final_enter(self):
        timeline = []
        elapsed = 0.0
        def wait(seconds):
            nonlocal elapsed
            elapsed += seconds
        def key(vk, down):
            timeline.append((vk, down, elapsed))
        self.sender.wait = wait
        self.api.key = key
        self.send("all")
        shift_down, enter_down, enter_up, shift_up, final_down, final_up = timeline
        self.assertEqual(self.api.batches, [((16, 13), True)])
        self.assertEqual(enter_down[2], shift_down[2])
        self.assertGreaterEqual(enter_up[2] - enter_down[2], 0.05)
        self.assertAlmostEqual(shift_up[2] - enter_up[2], 0.03)
        self.assertGreater(final_down[2], shift_up[2])
        self.assertEqual([e[:2] for e in (final_down, final_up)], [(13, True), (13, False)])

    def test_shared_cycle(self):
        for channel in ("team", "all", "team", "all"):
            self.send(channel)
            self.time += 0.5
        self.assertEqual([e for e in self.api.events if isinstance(e, str)], ["你", "好", "B", "C", "你", "好"])
        self.assertEqual(self.messages.index, 1)

    def test_long_message_adds_no_deliberate_typing_delay(self):
        for channel in ("team", "all"):
            totals = []
            for message in ("短", "你好😀ABC" * 20):
                with self.subTest(channel=channel, length=len(message)):
                    self.messages.replace([message])
                    self.api.events.clear()
                    waits = []
                    self.sender.wait = waits.append
                    self.time = max(self.time, self.sender.ready_at)
                    self.assertTrue(self.send(channel))
                    totals.append(sum(waits))
                    self.assertEqual("".join(e for e in self.api.events if isinstance(e, str)), message)
            self.assertAlmostEqual(totals[0], totals[1])

    def test_fast_typing_still_stops_between_characters(self):
        for interruption in ("focus", "modifier", "cancel"):
            with self.subTest(interruption=interruption):
                self.api.events.clear()
                self.api.foreground = (100, 200)
                self.api.modified = False
                self.sender.cancel.clear()
                self.time = max(self.time, self.sender.ready_at)
                def type_then_interrupt(value):
                    self.api.events.append(value)
                    if interruption == "focus":
                        self.api.foreground = None
                    elif interruption == "modifier":
                        self.api.modified = True
                    else:
                        self.sender.cancel.set()
                self.api.text_character = type_then_interrupt
                self.assertTrue(self.send("team"))
                self.assertEqual(self.api.events, [(13, True), (13, False), "你"])
                self.assertEqual(self.messages.index, 0)
                self.assertFalse(self.sender.busy)

    def test_shared_cooldown_and_boundary(self):
        self.send("team")
        self.time += 0.499
        self.assertFalse(self.send("all"))
        self.time = 10.5
        self.assertTrue(self.send("all"))

    def test_cooldown_starts_after_completion(self):
        def wait(_):
            self.time += 0.1
        self.sender.wait = wait
        self.send("team")
        self.assertAlmostEqual(self.sender.ready_at, self.time + 0.5)

    def test_busy_drops_both_channels_and_prevents_edits(self):
        reached, release = threading.Event(), threading.Event()
        def wait(_):
            reached.set()
            release.wait(2)
        self.sender.wait = wait
        self.assertTrue(self.sender.trigger("all"))
        self.assertTrue(reached.wait(2))
        try:
            self.assertFalse(self.sender.trigger("team"))
            self.assertFalse(self.sender.trigger("all"))
            with self.assertRaises(ValueError):
                self.sender.edit(lambda: self.messages.replace(["new"]))
        finally:
            release.set()
            self.sender.thread.join(2)
        self.assertEqual(self.messages.index, 1)

    def test_empty_no_input(self):
        self.messages.replace([])
        self.assertFalse(self.send("team"))
        self.assertEqual(self.api.events, [])

    def test_other_foreground_no_input(self):
        self.api.foreground = None
        self.assertFalse(self.send("all"))
        self.assertEqual(self.api.events, [])

    def test_foreground_rejection_reports_specific_failure(self):
        self.api.foreground = None
        self.api.target_error = "读取 Windows 进程列表失败（错误 5）"
        self.assertFalse(self.send("team"))
        self.assertIn("错误 5", self.reports[-1])
        self.assertEqual(self.api.events, [])

    def test_modifiers_no_input(self):
        self.api.modified = True
        self.assertFalse(self.send("team"))
        self.assertEqual(self.api.events, [])

    def test_focus_lost_releases_keys_does_not_advance(self):
        def lose_focus_during_chord(_):
            if (13, True) in self.api.events:
                self.api.foreground = None
        self.sender.wait = lose_focus_during_chord
        self.send("all")
        self.assertEqual(self.messages.index, 0)
        self.assertIn((16, False), self.api.events)
        self.assertIn((13, False), self.api.events)
        self.assertFalse(any(isinstance(e, str) for e in self.api.events))
        self.assertFalse(self.sender.busy)

    def test_partial_batch_releases_both_keys_without_text_or_advance(self):
        def partial_batch(virtual_keys, down):
            self.api.key(virtual_keys[0], down)
            raise OSError("SendInput 仅提交 1/2 个事件")
        self.api.keys = partial_batch
        self.send("all")
        self.assertEqual(self.api.events, [(16, True), (13, False), (16, False)])
        self.assertEqual(self.messages.index, 0)
        self.assertFalse(self.sender.busy)

    def test_cancel_after_enter_release_still_releases_shift(self):
        def cancel_during_tail(_):
            if (13, False) in self.api.events:
                self.sender.cancel.set()
        self.sender.wait = cancel_during_tail
        self.send("all")
        self.assertEqual(self.api.events, [(16, True), (13, True), (13, False), (16, False)])
        self.assertEqual(self.messages.index, 0)

    def test_input_failure_unlocks_and_preserves_index(self):
        self.api.fail_text = True
        self.send("team")
        self.assertEqual(self.messages.index, 0)
        self.assertFalse(self.sender.busy)
        self.assertIn("索引未推进", self.reports[-1])
        self.api.fail_text = False
        self.time = self.sender.ready_at
        self.assertTrue(self.send("all"))
        self.assertEqual(self.messages.index, 1)

    def test_partial_key_failure_releases_shift_and_enter(self):
        original = self.api.key
        def fail(vk, down):
            original(vk, down)
            if vk == 13 and down:
                raise OSError("partial input")
        self.api.key = fail
        self.send("all")
        self.assertIn((16, False), self.api.events)
        self.assertIn((13, False), self.api.events)
        self.assertEqual(self.messages.index, 0)

    def test_cancel_releases_and_does_not_advance(self):
        self.sender.wait = lambda _: self.sender.cancel.set()
        self.send("all")
        self.assertEqual(self.messages.index, 0)
        self.assertIn((16, False), self.api.events)
        self.assertFalse(self.send("team"))

    def test_restart_resets_index(self):
        self.messages.advance()
        self.assertEqual(MessageManager(self.messages.path).index, 0)

    def test_edit_resets_index_and_persists(self):
        self.messages.advance()
        self.messages.replace(["C", "你好"])
        self.assertEqual(self.messages.index, 0)
        self.assertEqual(MessageManager(self.messages.path).messages, ["C", "你好"])

    def test_corrupt_json_preserved(self):
        self.messages.path.write_bytes(b'{ broken')
        with self.assertRaises(ValueError):
            MessageManager(self.messages.path)
        self.assertEqual(self.messages.path.read_bytes(), b'{ broken')

    def test_wrong_schema_preserved(self):
        self.messages.path.write_text('{"messages":[]}', encoding="utf-8")
        with self.assertRaises(ValueError):
            MessageManager(self.messages.path)
        self.assertEqual(json.loads(self.messages.path.read_text()), {"messages": []})

    def test_write_failure_keeps_memory_and_original(self):
        old = self.messages.path.read_bytes()
        with patch("config_manager.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.messages.replace(["new"])
        self.assertEqual(self.messages.messages, ["你好", "B", "C"])
        self.assertEqual(self.messages.path.read_bytes(), old)
        self.assertEqual(list(self.path.glob("*.tmp")), [])

    def test_reject_control_characters(self):
        for value in ("", "  ", "A\nB", "A\rB", "a\tb", "\x00", "\ud800", "a\u2028b"):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                validate_messages([value])
        validate_messages(["你好 😀", "A B"])

    def test_txt_utf8_append_export_roundtrip(self):
        source = self.path / "import.txt"
        source.write_text("第一行\n\n第二行\n", encoding="utf-8-sig")
        self.messages.import_txt(source)
        self.assertEqual(self.messages.messages[-2:], ["第一行", "第二行"])
        self.messages.export_txt(self.path / "export.txt")
        other = MessageManager(self.path / "other.json")
        other.import_txt(self.path / "export.txt")
        self.assertEqual(other.messages, self.messages.messages)

    def test_gb18030_import(self):
        source = self.path / "gb.txt"
        source.write_bytes("中文消息".encode("gb18030"))
        self.messages.import_txt(source)
        self.assertEqual(self.messages.messages[-1], "中文消息")

    def test_config_defaults_and_validation(self):
        config = ConfigManager(self.path / "config.json")
        self.assertEqual(config.value, DEFAULT_CONFIG)
        for seconds in (0.2, 0.49, 0.5, 1.25, 2):
            with self.subTest(seconds=seconds):
                validate_config({**DEFAULT_CONFIG, "cooldown": seconds})
        for key, value in (("cooldown", 0.199), ("cooldown", 2.001),
                           ("cooldown", float("nan")), ("cooldown", True),
                           ("team_hotkey", "F12"), ("team_hotkey", "F9"), ("autostart", 1)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_config({**DEFAULT_CONFIG, key: value})

    def test_bad_config_is_not_overwritten(self):
        path = self.path / "config.json"
        path.write_text('{"cooldown": 0.1}', encoding="utf-8")
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            ConfigManager(path)
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

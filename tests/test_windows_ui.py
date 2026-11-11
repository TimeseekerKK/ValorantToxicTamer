"""Native bindings and offscreen widgets; never sends real keyboard input."""
import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from valorant_toxic_tamer.config_manager import ConfigManager, DEFAULT_CONFIG
from valorant_toxic_tamer.hotkey import Hotkeys
from valorant_toxic_tamer.app import Application
from valorant_toxic_tamer.message_manager import MessageManager
from valorant_toxic_tamer.sender import Sender
from valorant_toxic_tamer.ui import MainWindow
from valorant_toxic_tamer.win32_api import INPUT, KEYBDINPUT, PROCESSENTRY32W, WindowsAPI


class WindowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # Qt's offscreen plugin does not discover Windows system fonts itself.
        for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
            font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))

    def test_native_struct_layout(self):
        expected = 40 if C.sizeof(C.c_void_p) == 8 else 28
        self.assertEqual(C.sizeof(INPUT), expected)
        self.assertEqual(C.sizeof(KEYBDINPUT), 24 if expected == 40 else 16)
        self.assertEqual(C.sizeof(PROCESSENTRY32W), 568 if expected == 40 else 556)

    def snapshot_api(self, entries):
        api = WindowsAPI()
        api.kernel = Mock()
        api.kernel.CreateToolhelp32Snapshot.return_value = 123
        iterator = iter(entries)

        def next_process(handle, pointer):
            self.assertEqual(handle, 123)
            try:
                pid, name = next(iterator)
            except StopIteration:
                C.set_last_error(18)
                return 0
            entry = C.cast(pointer, C.POINTER(PROCESSENTRY32W)).contents
            self.assertEqual(entry.dwSize, C.sizeof(PROCESSENTRY32W))
            entry.th32ProcessID, entry.szExeFile = pid, name
            return 1

        api.kernel.Process32FirstW.side_effect = next_process
        api.kernel.Process32NextW.side_effect = next_process
        return api

    def test_game_name_resolves_without_opening_game_process(self):
        api = self.snapshot_api([(10, "other.exe"), (20, "VALORANT-Win64-Shipping.exe")])
        api.foreground = Mock(return_value=(100, 20))
        self.assertEqual(api.target(), (100, 20))
        api.kernel.OpenProcess.assert_not_called()
        api.kernel.QueryFullProcessImageNameW.assert_not_called()
        api.kernel.CreateToolhelp32Snapshot.assert_called_once_with(2, 0)
        api.kernel.CloseHandle.assert_called_once_with(123)

    def test_foreground_other_app_remains_blocked_with_specific_reason(self):
        for name in ("notepad.exe", "VALORANT.exe", "Fake-VALORANT-Win64-Shipping.exe"):
            with self.subTest(name=name):
                api = self.snapshot_api([(20, name)])
                api.foreground = Mock(return_value=(100, 20))
                self.assertIsNone(api.target())
                self.assertIn(name, api.target_error)

    def test_snapshot_failure_remains_blocked_and_reports_error(self):
        api = self.snapshot_api([])
        api.kernel.CreateToolhelp32Snapshot.return_value = C.c_void_p(-1).value
        api.foreground = Mock(return_value=(100, 20))
        C.set_last_error(5)
        self.assertIsNone(api.target())
        self.assertIn("错误 5", api.target_error)
        api.kernel.CloseHandle.assert_not_called()

    def test_missing_process_in_snapshot_remains_blocked(self):
        api = self.snapshot_api([(10, "other.exe")])
        api.foreground = Mock(return_value=(100, 20))
        self.assertIsNone(api.target())
        self.assertIn("PID 20", api.target_error)
        api.kernel.CloseHandle.assert_called_once_with(123)

    def test_focus_change_during_process_lookup_remains_blocked(self):
        api = self.snapshot_api([(20, "VALORANT-Win64-Shipping.exe")])
        api.foreground = Mock(side_effect=[(100, 20), (200, 30)])
        self.assertIsNone(api.target())
        self.assertIn("前台窗口发生变化", api.target_error)

    def test_during_send_same_hwnd_and_pid_required_without_rescanning(self):
        api = WindowsAPI()
        api.foreground = Mock(return_value=(100, 20))
        api.process_name = Mock()
        self.assertTrue(api.is_foreground((100, 20)))
        self.assertFalse(api.is_foreground((100, 30)))
        self.assertFalse(api.is_foreground((200, 20)))
        api.process_name.assert_not_called()

    def test_unicode_surrogates_are_paired_events(self):
        api = WindowsAPI()
        api.emit = Mock()
        api.text_character("😀")
        events = api.emit.call_args.args[0]
        self.assertEqual([e.ki.wScan for e in events], [0xD83D, 0xD83D, 0xDE00, 0xDE00])
        self.assertEqual([e.ki.dwFlags for e in events], [4, 6, 4, 6])
        self.assertTrue(all(e.ki.wVk == 0 for e in events))

    def test_short_sendinput_fails(self):
        api = WindowsAPI()
        api.user = Mock()
        api.user.SendInput.return_value = 0
        with self.assertRaises(OSError):
            api.key(13, True)

    def test_shift_uses_matching_left_scan_code_down_and_up(self):
        api = WindowsAPI()
        api.emit = Mock()
        api.key(16, True)
        api.key(16, False)
        events = [call.args[0][0].ki for call in api.emit.call_args_list]
        self.assertEqual([(e.wVk, e.wScan, e.dwFlags) for e in events],
                         [(0, 0x2A, 8), (0, 0x2A, 10)])

    def test_enter_keeps_existing_virtual_key_input(self):
        api = WindowsAPI()
        api.emit = Mock()
        api.key(13, True)
        api.key(13, False)
        events = [call.args[0][0].ki for call in api.emit.call_args_list]
        self.assertEqual([(e.wVk, e.wScan, e.dwFlags) for e in events],
                         [(13, 0, 0), (13, 0, 2)])

    def test_shift_enter_down_uses_one_sendinput_call_in_modifier_order(self):
        api = WindowsAPI()
        send_input = Mock(return_value=2)
        api.user = Mock()
        api.user.MapVirtualKeyW.return_value = 0x2A
        api.user.SendInput = send_input
        api.keys((16, 13), True)
        send_input.assert_called_once()
        count, events, size = send_input.call_args.args
        self.assertEqual((count, size), (2, C.sizeof(INPUT)))
        self.assertEqual([(e.ki.wVk, e.ki.wScan, e.ki.dwFlags) for e in events],
                         [(0, 0x2A, 8), (13, 0, 0)])

    def test_short_chord_batch_reports_failure(self):
        api = WindowsAPI()
        api.user = Mock()
        api.user.MapVirtualKeyW.return_value = 0x2A
        api.user.SendInput.return_value = 1
        with self.assertRaisesRegex(OSError, "1/2"):
            api.keys((16, 13), True)

    def test_shift_mapping_failure_does_not_emit_input(self):
        api = WindowsAPI()
        api.user = Mock()
        api.user.MapVirtualKeyW.return_value = 0
        api.emit = Mock()
        with self.assertRaises(OSError):
            api.key(16, True)
        api.emit.assert_not_called()

    def hotkeys(self):
        api = Mock()
        api.user.RegisterHotKey.return_value = 1
        api.kernel.GetTickCount64.return_value = 1000
        callback = Mock()
        hotkeys = Hotkeys(self.app, 100, api, callback)
        self.addCleanup(hotkeys.close)
        hotkeys.configure(DEFAULT_CONFIG)
        return hotkeys, api, callback

    def test_hotkeys_norepeat_and_cleanup(self):
        hotkeys, api, _ = self.hotkeys()
        self.assertEqual([c.args for c in api.user.RegisterHotKey.call_args_list],
                         [(100, 0x5101, 0x4000, 0x77), (100, 0x5102, 0x4000, 0x78)])
        hotkeys.unregister()
        self.assertEqual(api.user.UnregisterHotKey.call_count, 2)

    def test_hotkeys_keep_unchanged_registration_and_support_swaps(self):
        hotkeys, api, _ = self.hotkeys()
        api.user.RegisterHotKey.reset_mock()
        self.assertTrue(hotkeys.configure(DEFAULT_CONFIG))
        api.user.RegisterHotKey.assert_not_called()
        api.user.UnregisterHotKey.assert_not_called()
        self.assertTrue(hotkeys.configure({**DEFAULT_CONFIG, "team_hotkey": "F7"}))
        api.user.UnregisterHotKey.assert_called_once_with(100, 0x5101)
        api.user.RegisterHotKey.assert_called_once_with(100, 0x5101, 0x4000, 0x76)
        api.user.RegisterHotKey.reset_mock()
        api.user.UnregisterHotKey.reset_mock()
        self.assertTrue(hotkeys.configure({**DEFAULT_CONFIG, "team_hotkey": "F9", "all_hotkey": "F7"}))
        self.assertEqual(api.user.UnregisterHotKey.call_count, 2)
        self.assertEqual(hotkeys.registered, {0x5101: "F9", 0x5102: "F7"})

    def test_native_filter_discards_stale_requests(self):
        hotkeys, _, callback = self.hotkeys()
        msg = W.MSG(message=0x312, wParam=0x5101, time=1000)
        hotkeys.nativeEventFilter(QByteArray(b"windows_generic_MSG"), C.addressof(msg))
        callback.assert_called_once_with("team")
        msg.time = 800
        hotkeys.nativeEventFilter(QByteArray(b"windows_generic_MSG"), C.addressof(msg))
        self.assertEqual(callback.call_count, 1)

    def test_conflicting_hotkey_status(self):
        hotkeys, api, _ = self.hotkeys()
        hotkeys.unregister()
        api.user.RegisterHotKey.return_value = 0
        self.assertFalse(hotkeys.configure(DEFAULT_CONFIG))
        self.assertEqual(hotkeys.registered, {})
        self.assertIn("注册失败", hotkeys.status["team"])

    def test_settings_conflict_rolls_back_without_registry_write(self):
        controller = Mock()
        controller.config.value = DEFAULT_CONFIG.copy()
        controller.hotkeys.configure.side_effect = [False, True]
        controller.hotkeys.status = {"team": "冲突", "all": "注册成功"}
        from unittest.mock import patch
        with patch("valorant_toxic_tamer.app.set_autostart") as registry:
            with self.assertRaises(ValueError):
                Application.save_settings(controller, {**DEFAULT_CONFIG, "autostart": True, "team_hotkey": "F7"})
            registry.assert_not_called()
        controller.config.save.assert_not_called()

    def test_cooldown_keyboard_edit_save_reload_and_shared_boundary(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            directory = Path(directory)
            config = ConfigManager(directory / "config.json")
            messages = MessageManager(directory / "messages.json")
            messages.replace(["测试消息"])
            api = Mock()
            api.target.return_value = (100, 200)
            api.modifiers_down.return_value = False
            now = [10.0]
            sender = Sender(messages, api, clock=lambda: now[0], wait=lambda _: None)
            controller = Mock(config=config, sender=sender)
            controller.hotkeys.configure.return_value = True
            controller.hotkeys.status = {"team": "F8", "all": "F9"}
            window = MainWindow(messages, config, sender,
                                lambda value: Application.save_settings(controller, value))
            controller.window = window
            try:
                window.show()
                window.tabs.setCurrentIndex(1)
                self.app.processEvents()
                for seconds in (0.2, 0.49, 0.8, 2.0, 0.5):
                    with self.subTest(seconds=seconds):
                        window.cooldown.setFocus()
                        window.cooldown.selectAll()
                        QTest.keyClicks(window.cooldown, str(seconds))
                        QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
                        self.assertEqual(config.value["cooldown"], seconds)
                        self.assertEqual(ConfigManager(config.path).value["cooldown"], seconds)
                        self.assertEqual(sender.cooldown, seconds)
                        self.assertEqual(window.result_label.text(), "设置已保存。")
                        window.load_settings()
                        self.assertEqual(float(window.cooldown.text()), seconds)
                        now[0] = max(now[0], sender.ready_at)
                        self.assertTrue(sender.trigger("team"))
                        sender.thread.join(2)
                        self.assertFalse(sender.thread.is_alive())
                        self.assertAlmostEqual(sender.ready_at, now[0] + seconds)
                        now[0] = sender.ready_at - 0.001
                        self.assertFalse(sender.trigger("all"))
                        now[0] = sender.ready_at
                        self.assertTrue(sender.trigger("all"))
                        sender.thread.join(2)
                        self.assertFalse(sender.thread.is_alive())
            finally:
                sender.stop()
                window.timer.stop()
                window.hide()
                window.deleteLater()
                self.app.processEvents()

    def test_invalid_cooldown_is_reported_instead_of_silently_changed(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            directory = Path(directory)
            config = ConfigManager(directory / "config.json")
            messages = MessageManager(directory / "messages.json")
            sender = Sender(messages, Mock())
            controller = Mock(config=config, sender=sender)
            window = MainWindow(messages, config, sender,
                                lambda value: Application.save_settings(controller, value))
            window.error = Mock()
            before = config.path.read_bytes()
            try:
                window.show()
                window.tabs.setCurrentIndex(1)
                self.app.processEvents()
                for text in ("30", "2.01", "0.19", "nan", "abc", ""):
                    with self.subTest(text=text):
                        window.error.reset_mock()
                        window.cooldown.setFocus()
                        window.cooldown.selectAll()
                        QTest.keyClick(window.cooldown, Qt.Key.Key_Backspace)
                        QTest.keyClicks(window.cooldown, text)
                        QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
                        window.error.assert_called_once()
                        self.assertEqual(config.path.read_bytes(), before)
                        self.assertEqual(sender.cooldown, DEFAULT_CONFIG["cooldown"])
                controller.hotkeys.configure.assert_not_called()
            finally:
                window.timer.stop()
                window.hide()
                window.deleteLater()
                self.app.processEvents()

    def test_widgets_render_and_close_to_background(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            directory = Path(directory)
            messages = MessageManager(directory / "messages.json")
            messages.replace(["我们一起配合，下一局加油！", "谢谢队友，打得漂亮。", "注意侧面，等大家一起进点。"])
            config = ConfigManager(directory / "config.json")
            sender = Sender(messages, Mock())
            window = MainWindow(messages, config, sender, Mock())
            try:
                window.set_hotkey_status({"team": "F8 · 已注册（界面示例）", "all": "F9 · 已注册（界面示例）"})
                window.show()
                self.app.processEvents()
                self.assertTrue(window.isVisible())
                self.assertEqual(window.list_widget.count(), 3)
                self.assertIn("1 / 3", window.state_label.text())
                window.list_widget.setCurrentRow(1)
                window.move(-1)
                self.assertEqual(messages.messages[0], "谢谢队友，打得漂亮。")
                self.assertEqual(MessageManager(messages.path).messages, messages.messages)
                output = Path(__file__).resolve().parents[1] / "artifacts" / "screenshots"
                output.mkdir(parents=True, exist_ok=True)
                self.assertTrue(window.grab().save(str(output / "main-window.png")))
                window.tabs.setCurrentIndex(1)
                self.app.processEvents()
                self.assertTrue(window.grab().save(str(output / "settings.png")))
                window.close()
                self.app.processEvents()
                self.assertFalse(window.isVisible())
            finally:
                window.timer.stop()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()

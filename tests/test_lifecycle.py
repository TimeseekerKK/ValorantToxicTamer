"""Cold-start imports and UI lifecycle regressions; no game input or network."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from valorant_toxic_tamer.app import Application
from valorant_toxic_tamer.config_manager import ConfigManager
from valorant_toxic_tamer.message_manager import MessageManager
from valorant_toxic_tamer.sender import Sender
from valorant_toxic_tamer.ui import MainWindow


class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        root = Path(self.temp.name)
        self.config = ConfigManager(root / "config.json")
        self.messages = MessageManager(root / "messages.json")
        self.messages.replace(["第一条", "第二条"])
        self.sender = Sender(self.messages, Mock())
        self.window = MainWindow(self.messages, self.config, self.sender, self.config.save)

    def tearDown(self):
        self.window.updater.shutdown()
        self.sender.stop()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_settings_load_on_first_visit_and_preserve_unsaved_edits(self):
        self.window.show()
        self.assertFalse(self.window.settings_loaded)
        self.assertFalse(hasattr(self.window, "update_button"))
        self.window.tabs.setCurrentIndex(1)
        self.assertTrue(self.window.settings_loaded)
        self.assertEqual(self.window.cooldown.text(), str(self.config.value["cooldown"]))
        self.window.cooldown.setText("1.8")
        self.window.tabs.setCurrentIndex(0)
        self.window.tabs.setCurrentIndex(1)
        self.assertEqual(self.window.cooldown.text(), "1.8")
        self.assertIn("未保存", self.window.settings_hint.text())

    def test_hidden_window_stops_polling_and_refreshes_latest_state_on_show(self):
        ticks = []
        self.window.timer.timeout.connect(lambda: ticks.append(1))
        self.sender.busy = True
        self.window.show()
        QTest.qWait(150)
        self.assertTrue(ticks)
        self.window.close()
        self.assertFalse(self.window.timer.isActive())
        count = len(ticks)
        self.messages.advance()
        self.sender.busy = False
        QTest.qWait(150)
        self.assertEqual(len(ticks), count)
        self.window.reveal()
        self.assertEqual(self.window.next_label.text(), "第二条")
        self.assertFalse(self.window.timer.isActive())

    def test_polling_only_runs_during_visible_send_or_cooldown(self):
        now = [10.0]
        self.sender.clock = lambda: now[0]
        self.window.show()
        self.assertFalse(self.window.timer.isActive())
        self.sender.ready_at = 11.0
        self.window.report("输入完成")
        self.assertTrue(self.window.timer.isActive())
        self.assertIn("冷却", self.window.state_label.text())
        now[0] = 11.1
        QTest.qWait(150)
        self.assertFalse(self.window.timer.isActive())
        self.assertIn("就绪", self.window.state_label.text())

    def test_hotkey_failure_opens_settings_and_hidden_start_can_exit_without_ui(self):
        api = Mock()
        for registered in (True, False):
            with self.subTest(registered=registered):
                api.user.RegisterHotKey.return_value = int(registered)
                with patch("valorant_toxic_tamer.app.WindowsAPI", return_value=api):
                    controller = Application(self.app, self.config.path.parent)
                try:
                    controller.tray.menu.ensurePolished()
                    self.assertEqual(controller.tray.menu.font().pixelSize(), controller.config.value["font_size"])
                    if registered:
                        self.assertIsNone(controller.window)
                        controller.save_settings({**controller.config.value, "font_size": 16})
                        controller.tray.menu.ensurePolished()
                        self.assertEqual(controller.tray.menu.font().pixelSize(), 16)
                    else:
                        self.assertTrue(controller.window.isVisible())
                        self.assertEqual(controller.window.tabs.currentIndex(), 1)
                finally:
                    self.app.aboutToQuit.disconnect(controller.cleanup)
                    controller.cleanup()
                    if controller.window is not None:
                        controller.window.hide()
                        controller.window.deleteLater()
                    controller.tray.deleteLater()
                    controller.deleteLater()
                    self.app.processEvents()

    def test_cold_process_defers_ui_and_update_dependencies(self):
        code = '''
import sys, tempfile
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from valorant_toxic_tamer import app as module
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
module.WindowsAPI = lambda: SimpleNamespace(user=SimpleNamespace(
    RegisterHotKey=lambda *args: 1, UnregisterHotKey=lambda *args: 1))
with tempfile.TemporaryDirectory(dir='tests') as directory:
    controller = module.Application(app, Path(directory))
    assert controller.window is None
    assert 'valorant_toxic_tamer.ui' not in sys.modules
    assert 'valorant_toxic_tamer.updater' not in sys.modules
    assert 'ssl' not in sys.modules and 'truststore' not in sys.modules
    handle = controller.hotkeys.hwnd
    controller.report('队伍输入完成')
    assert controller.window is None
    controller.tray.menu.actions()[0].trigger()
    assert controller.window.isVisible()
    assert not controller.window.settings_loaded
    assert controller.window.result_label.text() == '队伍输入完成'
    controller.tray.menu.actions()[2].trigger()
    assert controller.window.settings_loaded
    assert 'valorant_toxic_tamer.updater' not in sys.modules
    assert 'ssl' not in sys.modules and 'truststore' not in sys.modules
    import time
    from valorant_toxic_tamer import update_process
    def fixture_command(channel, path):
        code = ("import sys,json; import valorant_toxic_tamer.updater; "
                "assert 'ssl' in sys.modules and 'truststore' in sys.modules; "
                "open(sys.argv[1], 'w', encoding='utf-8').write(json.dumps(dict(release=None,error=None)))")
        return [sys.executable, '-B', '-c', code, str(path)]
    update_process.worker_command = fixture_command
    errors = []
    controller.window.error = errors.append
    controller.window.information = lambda *args: None
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.exec = lambda self: QMessageBox.StandardButton.No
    for attempt in range(3):
        controller.window.update_button.click()
        deadline = time.monotonic() + 10
        while controller.window.updater.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert not controller.window.updater.busy
        assert 'valorant_toxic_tamer.updater' not in sys.modules
        assert 'ssl' not in sys.modules and 'truststore' not in sys.modules
    controller.window.close()
    controller.reveal()
    assert controller.hotkeys.hwnd == handle
    assert controller.tray.isVisible()
    controller.window.close()
    controller.cleanup()
    assert not controller.hotkeys.registered
    assert controller.sender.cancel.is_set()
print('cold lifecycle passed')
'''
        result = subprocess.run([sys.executable, "-B", "-c", code],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("cold lifecycle passed", result.stdout)

    def test_quit_keeps_event_loop_running_until_update_worker_stops(self):
        api = Mock()
        api.user.RegisterHotKey.return_value = 1
        with patch("valorant_toxic_tamer.app.WindowsAPI", return_value=api):
            controller = Application(self.app, self.config.path.parent)
        entered = threading.Event()

        def lookup(*, channel, cancel):
            entered.set()
            cancel.wait(3)
            time.sleep(0.2)  # Simulate resource cleanup after cancellation.
            raise ValueError("已取消")

        try:
            controller.reveal(1)
            controller.window.error = Mock()
            ticks = []
            with patch("valorant_toxic_tamer.update_process.check_for_update", side_effect=lookup), \
                    patch.object(self.app, "quit") as quit_app:
                controller.window.update_button.click()
                self.assertTrue(entered.wait(1))
                began = time.monotonic()
                controller.quit()
                self.assertLess(time.monotonic() - began, 0.1)
                self.assertTrue(controller.window.updater.cancel.is_set())
                self.assertFalse(controller.trigger("team"))
                QTimer.singleShot(0, lambda: ticks.append(True))
                QTest.qWait(40)
                self.assertTrue(ticks)
                quit_app.assert_not_called()
                deadline = time.monotonic() + 3
                while not quit_app.called and time.monotonic() < deadline:
                    QTest.qWait(10)
                quit_app.assert_called_once()
                controller.window.error.assert_not_called()
        finally:
            self.app.aboutToQuit.disconnect(controller.cleanup)
            controller.cleanup()
            controller.window.hide()
            controller.window.deleteLater()
            controller.tray.deleteLater()
            controller.deleteLater()
            self.app.processEvents()

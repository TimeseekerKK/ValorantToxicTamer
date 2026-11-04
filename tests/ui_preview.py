"""Opt-in real-window UI preview with temporary data and no registered hotkeys.

Run: .venv/Scripts/pythonw.exe tests/ui_preview.py
Close the preview to exit. This never invokes game input or network requests.
"""
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from valorant_toxic_tamer.config_manager import ConfigManager
from valorant_toxic_tamer.message_manager import MessageManager
from valorant_toxic_tamer.sender import Sender
from valorant_toxic_tamer.ui import MainWindow


class PreviewWindow(MainWindow):
    def closeEvent(self, event):
        event.accept()
        QApplication.instance().quit()


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts" / "ui-redesign"
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    with tempfile.TemporaryDirectory(prefix="preview-", dir=output) as directory:
        directory = Path(directory)
        messages = MessageManager(directory / "messages.json")
        messages.replace(["谢谢队友，打得漂亮。", "我们一起配合，下一局加油！",
                          "注意侧面，等大家一起进点。", "先稳住，我们还有机会。", "辛苦了，下一把见。"])
        messages.advance()
        config = ConfigManager(directory / "config.json")
        sender = Sender(messages, Mock())
        window = PreviewWindow(messages, config, sender, config.save)
        window.setWindowTitle("ValorantToxicTamer · UI 预览")
        window.set_hotkey_status({"team": "F8 · 预览（未注册）", "all": "F9 · 预览（未注册）"})
        window.list_widget.setCurrentRow(3)
        window.show()

        def capture():
            window.grab().save(str(output / "main-native.png"))
            window.tabs.setCurrentIndex(1)
            app.processEvents()
            window.grab().save(str(output / "settings-native.png"))
            window.tabs.setCurrentIndex(0)
            (output / "native-platform.txt").write_text(app.platformName(), encoding="utf-8")

        QTimer.singleShot(500, capture)
        # Avoid orphaning a preview process if the inspection is interrupted.
        QTimer.singleShot(15 * 60 * 1000, app.quit)
        app.exec()
        window.timer.stop()
        window.updater.shutdown()
        sender.stop()


if __name__ == "__main__":
    main()

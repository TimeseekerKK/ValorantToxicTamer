"""Run update networking away from the GUI thread."""
import threading

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QMessageBox

from .app_version import VERSION
from .config_manager import atomic_json, load_json
from .updater import (UPDATE_CHANNELS, download_release, installed_executable,
                      latest_release, launch_installer, version_tuple)
from .ui_theme import style_message_box


class UpdateWorker(QThread):
    def __init__(self, action, parent):
        super().__init__(parent)
        self.action = action
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.action()
        except Exception as exc:
            self.error = str(exc)


class UpdateController(QObject):
    ready_to_install = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.worker = None
        self.cancel = threading.Event()
        self.busy = False
        self.closing = False
        self.stage = None
        self.target = None
        # Older official versions ignore this file, so switching back remains compatible.
        self.preferences_path = window.config.path.with_name("update_settings.json")
        def validate(value):
            if not isinstance(value, dict) or set(value) != {"channel"} or value["channel"] not in UPDATE_CHANNELS:
                raise ValueError("更新渠道设置无效。")
        self.channel = load_json(self.preferences_path, {"channel": "stable"}, validate)["channel"]
        window.update_channel.setCurrentIndex(window.update_channel.findData(self.channel))
        window.update_channel.currentIndexChanged.connect(self.change_channel)
        self._channel_hint()

    def _channel_hint(self):
        self.window.update_channel_hint.setText(
            "仅接收正式版；从 Beta 切回时会提示降级。" if self.channel == "stable" else
            "接收正式版和 Beta，选择版本号最高的版本。测试功能可能尚不稳定。")
        self.window.update_channel.setToolTip("选择后自动保存，下次启动保留。")

    @Slot()
    def change_channel(self):
        channel = self.window.update_channel.currentData()
        try:
            atomic_json(self.preferences_path, {"channel": channel})
        except OSError as exc:
            self.window.update_channel.blockSignals(True)
            self.window.update_channel.setCurrentIndex(self.window.update_channel.findData(self.channel))
            self.window.update_channel.blockSignals(False)
            self.window.error(exc)
            return
        self.channel = channel
        self._channel_hint()

    @Slot()
    def check(self):
        if self.busy or self.closing:
            return
        self.busy = True
        self.window.update_button.setEnabled(False)
        self.window.update_button.set_busy(True)
        self.window.update_channel.setEnabled(False)
        self.window.update_button.setText("检查中…")
        self.window.result_label.setText("正在检查更新…")
        channel = self.channel
        self._start("check", lambda: latest_release(channel=channel))

    def _start(self, stage, action):
        self.stage = stage
        self.worker = UpdateWorker(action, self)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _idle(self):
        self.busy = False
        self.window.update_button.setEnabled(True)
        self.window.update_button.set_busy(False)
        self.window.update_channel.setEnabled(True)
        self.window.update_button.setText("检查更新")

    @Slot()
    def _finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        if self.closing:
            if self.stage == "download" and worker.result:
                worker.result.unlink(missing_ok=True)
            return
        if worker.error:
            self._idle()
            self.window.result_label.setText("检查更新失败。" if self.stage == "check" else "更新未完成。")
            self.window.error(worker.error)
            return
        if self.stage == "check":
            release = worker.result
            if release is None:
                self._idle()
                self.window.result_label.setText("当前已是最新版本。")
                self.window.information("检查更新", f"{UPDATE_CHANNELS[self.channel]}：当前已是最新版本。")
                return
            dialog = QMessageBox(self.window)
            dialog.setWindowTitle("检查更新")
            dialog.setIcon(QMessageBox.Icon.Question)
            dialog.setText("发现新版本,是否更新")
            downgrade = version_tuple(release.version) < version_tuple(VERSION)
            if downgrade:
                dialog.setIcon(QMessageBox.Icon.Warning)
                dialog.setText("切回正式版（降级）？")
            detail = "\n目标正式版低于当前 Beta，此操作将降级程序。" if downgrade else ""
            dialog.setInformativeText(
                f"更新渠道：{UPDATE_CHANNELS[self.channel]}\n当前版本：v{VERSION}\n目标版本：{release.version}"
                f"{detail}\n确认后将下载更新，退出当前程序并覆盖 EXE，然后重新启动。")
            dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            dialog.button(QMessageBox.StandardButton.Yes).setText("是")
            dialog.button(QMessageBox.StandardButton.No).setText("否")
            dialog.setDefaultButton(QMessageBox.StandardButton.No)
            style_message_box(dialog, QMessageBox.StandardButton.Yes)
            answer = dialog.exec()
            dialog.deleteLater()
            if answer != QMessageBox.StandardButton.Yes or self.closing:
                self._idle()
                self.window.result_label.setText("已取消更新。")
                return
            try:
                self.target = installed_executable()
            except ValueError as exc:
                self._idle()
                self.window.error(exc)
                return
            self.window.result_label.setText("正在下载更新，请稍候…")
            self.window.update_button.setText("下载中…")
            self._start("download", lambda: download_release(release, self.target, self.cancel))
        elif self.stage == "download":
            staged = worker.result
            def prepare():
                try:
                    launch_installer(staged, self.target)
                except Exception:
                    staged.unlink(missing_ok=True)
                    raise
            self.window.result_label.setText("正在准备覆盖安装…")
            self.window.update_button.setText("准备安装…")
            self._start("install", prepare)
        else:
            self.window.result_label.setText("更新已准备就绪，正在退出并覆盖安装…")
            self.ready_to_install.emit()

    def shutdown(self):
        self.closing = True
        self.window.update_button.set_busy(False)
        self.cancel.set()
        if self.worker:
            self.worker.wait()
            if self.stage == "download" and self.worker.result:
                self.worker.result.unlink(missing_ok=True)

"""Run update networking away from the GUI thread."""
import threading
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QMessageBox

from .app_version import VERSION
from .config_manager import atomic_json, load_json
from .update_settings import UPDATE_CHANNELS
from .update_protocol import installed_executable, version_tuple
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
    download_progress = Signal(object, object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.worker = None
        self.cancel = threading.Event()
        self.busy = False
        self.closing = False
        self.stage = None
        self.target = None
        self.download_progress.connect(self._progress)
        # Older official versions ignore this file, so switching back remains compatible.
        self.preferences_path = window.config.path.with_name("update_settings.json")
        def validate(value):
            if not isinstance(value, dict) or set(value) != {"channel"} or value["channel"] not in UPDATE_CHANNELS:
                raise ValueError("更新渠道设置无效。")
        self.preferences_error = None
        try:
            self.channel = load_json(self.preferences_path, {"channel": "stable"}, validate)["channel"]
        except ValueError as exc:
            # Updating is optional: an unreadable preference must not disable the UI.
            self.channel = "stable"
            self.preferences_error = str(exc)

    def bind_widgets(self):
        window = self.window
        window.update_channel.setCurrentIndex(window.update_channel.findData(self.channel))
        window.update_channel.currentIndexChanged.connect(self.change_channel)
        window.repair_update_button.clicked.connect(self.repair_preferences)
        self._channel_hint()

    @Slot(object, object)
    def _progress(self, received, total):
        if self.closing or self.cancel.is_set() or self.stage != "download":
            return
        percent = received * 100 / total
        self.window.update_progress.setValue(received * 1000 // total)
        self.window.update_progress.setFormat(
            f"{percent:.1f}% · {received / 2**20:.1f} / {total / 2**20:.1f} MiB")

    @Slot()
    def cancel_update(self):
        if not self.busy or self.stage not in ("check", "download"):
            return
        self.cancel.set()
        self.window.cancel_update_button.setEnabled(False)
        self.window.result_label.setText("正在取消更新…")

    def _channel_hint(self):
        self.window.update_channel_hint.setText(
            "仅接收正式版；从 Beta 切回时会提示降级。" if self.channel == "stable" else
            "接收正式版和 Beta，选择版本号最高的版本。测试功能可能尚不稳定。")
        self.window.update_channel.setToolTip("选择后自动保存，下次启动保留。")
        self.window.repair_update_button.setVisible(self.preferences_error is not None)
        if self.preferences_error:
            self.window.update_channel_hint.setText(
                "更新设置无法读取，暂用正式版渠道。原文件已保留；恢复设置或切换渠道时会先备份原文件。")
            self.window.update_channel_hint.setToolTip(self.preferences_error)
        else:
            self.window.update_channel_hint.setToolTip("")

    def _save_preferences(self, channel):
        backup = None
        if self.preferences_error and self.preferences_path.exists():
            # Copy before replacing; a failed backup must leave the source intact.
            with tempfile.NamedTemporaryFile(dir=self.preferences_path.parent,
                    prefix="update_settings.invalid-", suffix=".json", delete=False) as stream:
                backup = Path(stream.name)
            try:
                shutil.copyfile(self.preferences_path, backup)
            except OSError:
                backup.unlink(missing_ok=True)
                raise
        atomic_json(self.preferences_path, {"channel": channel})
        self.channel = channel
        self.preferences_error = None
        self._channel_hint()
        if backup:
            self.window.result_label.setText(f"更新设置已恢复，原文件备份：{backup}")

    @Slot()
    def repair_preferences(self):
        if self.busy:
            return
        try:
            self._save_preferences(self.channel)
        except OSError as exc:
            self.window.error(exc)

    @Slot()
    def change_channel(self):
        channel = self.window.update_channel.currentData()
        try:
            self._save_preferences(channel)
        except OSError as exc:
            self.window.update_channel.blockSignals(True)
            self.window.update_channel.setCurrentIndex(self.window.update_channel.findData(self.channel))
            self.window.update_channel.blockSignals(False)
            self.window.error(exc)
            return

    @Slot()
    def check(self):
        if self.busy or self.closing:
            return
        self.cancel.clear()
        self.busy = True
        self.window.cancel_update_button.setEnabled(True)
        self.window.cancel_update_button.show()
        self.window.update_progress.hide()
        self.window.update_button.setEnabled(False)
        self.window.update_button.set_busy(True)
        self.window.update_channel.setEnabled(False)
        self.window.repair_update_button.setEnabled(False)
        self.window.update_button.setText("检查中…")
        self.window.result_label.setText("正在检查更新…")
        channel = self.channel
        def lookup():
            from .update_process import check_for_update
            return check_for_update(channel=channel, cancel=self.cancel)
        self._start("check", lookup)

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
        self.window.repair_update_button.setEnabled(True)
        self.window.update_button.setText("检查更新")
        self.window.cancel_update_button.hide()
        self.window.update_progress.hide()

    @Slot()
    def _finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        if self.closing:
            if self.stage == "download" and worker.result:
                worker.result.unlink(missing_ok=True)
            return
        if self.cancel.is_set() and self.stage in ("check", "download"):
            if self.stage == "download" and worker.result:
                worker.result.unlink(missing_ok=True)
            self._idle()
            self.window.result_label.setText("已取消更新。")
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
            self.window.update_progress.setValue(0)
            self.window.update_progress.setFormat("0.0%")
            self.window.update_progress.show()
            def download():
                from .update_process import download_update
                return download_update(release, self.target, self.cancel, progress=self.download_progress.emit)
            self._start("download", download)
        elif self.stage == "download":
            # Cancellation is allowed up to this handoff, never during EXE replacement.
            self.window.cancel_update_button.hide()
            self.window.update_progress.hide()
            staged = worker.result
            def prepare():
                try:
                    from .updater import launch_installer
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

    def begin_shutdown(self):
        self.closing = True
        if hasattr(self.window, "update_button"):
            self.window.update_button.set_busy(False)
        self.cancel.set()

    def shutdown(self):
        self.begin_shutdown()
        if self.worker:
            self.worker.wait()
            if self.stage == "download" and self.worker.result:
                self.worker.result.unlink(missing_ok=True)

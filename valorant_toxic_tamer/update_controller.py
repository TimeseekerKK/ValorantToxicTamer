"""Run update networking away from the GUI thread."""
import threading

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QMessageBox

from .updater import download_release, installed_executable, latest_release, launch_installer
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

    @Slot()
    def check(self):
        if self.busy or self.closing:
            return
        self.busy = True
        self.window.update_button.setEnabled(False)
        self.window.update_button.setText("检查中…")
        self.window.result_label.setText("正在检查更新…")
        self._start("check", latest_release)

    def _start(self, stage, action):
        self.stage = stage
        self.worker = UpdateWorker(action, self)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _idle(self):
        self.busy = False
        self.window.update_button.setEnabled(True)
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
            self.window.result_label.setText("更新未完成。")
            self.window.error(worker.error)
            return
        if self.stage == "check":
            release = worker.result
            if release is None:
                self._idle()
                self.window.result_label.setText("当前已是最新版本。")
                self.window.information("检查更新", "当前已是最新版本。")
                return
            dialog = QMessageBox(self.window)
            dialog.setWindowTitle("检查更新")
            dialog.setIcon(QMessageBox.Icon.Question)
            dialog.setText("发现新版本,是否更新")
            dialog.setInformativeText(f"最新版本：{release.version}\n确认后将下载更新，退出当前程序并覆盖 EXE，然后重新启动。")
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
        self.cancel.set()
        if self.worker:
            self.worker.wait()
            if self.stage == "download" and self.worker.result:
                self.worker.result.unlink(missing_ok=True)

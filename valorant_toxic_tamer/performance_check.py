"""Opt-in isolated performance probes: temporary data, no hotkeys or network."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def fixture_update_worker(result_path):
    # Exercise real TLS imports in the disposable update process, without HTTP.
    from . import updater  # noqa: F401
    Path(result_path).write_text('{"release": null, "error": null}', encoding="utf-8")
    return 0


def process_memory():
    import ctypes as C
    from ctypes import wintypes as W

    class Counters(C.Structure):
        _fields_ = [("cb", W.DWORD), ("PageFaultCount", W.DWORD)] + [
            (name, C.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
            "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
            "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]

    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = W.HANDLE
    psapi = C.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [W.HANDLE, C.POINTER(Counters), W.DWORD]
    psapi.GetProcessMemoryInfo.restype = W.BOOL
    counters = Counters()
    counters.cb = C.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), C.byref(counters), counters.cb):
        raise C.WinError(C.get_last_error())
    return {"working_set_MiB": round(counters.WorkingSetSize / 2**20, 3),
            "private_commit_MiB": round(counters.PrivateUsage / 2**20, 3)}


def run(report_path, started):
    from PySide6.QtCore import qVersion, Qt
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase, QFontInfo
    from . import app as application
    from .app_version import VERSION
    from . import update_process
    from .message_manager import prepare_txt_import

    # Retain the real application lifecycle without claiming the user's hotkeys.
    class ProbeHotkeys:
        def __init__(self, *args):
            self.status = {"team": "F8 · 性能检查（未注册）", "all": "F9 · 性能检查（未注册）"}

        def configure(self, config):
            return True

        def close(self):
            pass

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    # The offscreen Windows plugin needs explicit fonts to measure real glyphs.
    if app.platformName() == "offscreen":
        for name in ("msyh.ttc", "segoeui.ttf"):
            font = Path(os.environ["SystemRoot"]) / "Fonts" / name
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))
    application.Hotkeys = ProbeHotkeys
    result = {"schema": 1, "version": VERSION, "python": sys.version.split()[0],
              "qt": qVersion(), "platform": app.platformName(),
              "mode": "isolated-no-hotkeys-no-network", "frozen": bool(getattr(sys, "frozen", False)),
              "message_count": 5000, "metrics": {}, "samples": []}
    metrics = result["metrics"]

    def sample(stage, since):
        elapsed = round((time.perf_counter() - since) * 1000, 3)
        memory = process_memory()
        result["samples"].append({"stage": stage, "elapsed_ms": elapsed, **memory})
        metrics[f"{stage}.elapsed_ms"] = elapsed
        for name, value in memory.items():
            metrics[f"{stage}.{name}"] = value

    path = Path(report_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="performance-", dir=path.parent) as directory:
        controller = application.Application(app, Path(directory))
        sample("hidden_start", started)
        began = time.perf_counter()
        controller.reveal()
        app.processEvents()
        sample("window_open", began)
        window = controller.window
        management = getattr(window, "management", window)
        result["font_family"] = QFontInfo(window.font()).family()
        try:
            began = time.perf_counter()
            window.tabs.setCurrentIndex(1)
            app.processEvents()
            sample("settings_open", began)
            window.tabs.setCurrentIndex(0)
            began = time.perf_counter()
            controller.messages.replace([f"性能消息 {i:05d}，保持配合。" for i in range(5000)])
            window.reload_messages()
            app.processEvents()
            sample("load_5000", began)
            began = time.perf_counter()
            management.search.setText("00499")
            management.filter_messages()
            app.processEvents()
            sample("search_5000", began)
            management.search.clear()
            management.filter_messages()
            source = Path(directory) / "import.txt"
            source.write_text("\n".join(f"导入消息 {i}" for i in range(1000)), encoding="utf-8")
            began = time.perf_counter()
            preview = prepare_txt_import(source, controller.messages.messages)
            sample("prepare_import_1000", began)
            began = time.perf_counter()
            controller.messages.replace(controller.messages.messages + list(preview.unique_messages))
            window.reload_messages()
            app.processEvents()
            sample("apply_import_1000", began)
            # The same public operations can probe both the reference commit
            # and the candidate with an identical harness and temporary data.
            for count in (5000, 20000):
                controller.messages.replace([f"性能消息 {i:05d}，保持配合。" for i in range(count)])
                controller.messages.select_categories(["all"])
                window.reload_messages()
                app.processEvents()
                began = time.perf_counter()
                management.send_categories.item(0).setCheckState(Qt.CheckState.Unchecked)
                app.processEvents()
                sample(f"select_{count}", began)
                began = time.perf_counter()
                controller.messages.edit_message(count // 2, "已修改的性能消息，保持配合。")
                window.reload_messages(count // 2)
                app.processEvents()
                sample(f"edit_{count}", began)
                began = time.perf_counter()
                controller.messages.edit_message(0, "长消息：" + "注意配合，等待队友。" * 80)
                window.reload_messages(0)
                app.processEvents()
                sample(f"long_edit_{count}", began)
            window.information = lambda *args: None
            errors = []
            window.error = errors.append
            original_command = update_process.worker_command
            def fixture_command(channel, output):
                args = ["--performance-update-worker", str(output)]
                return ([sys.executable, *args] if getattr(sys, "frozen", False) else
                        [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py"), *args])
            update_process.worker_command = fixture_command
            try:
                for attempt in range(1, 4):
                    began = time.perf_counter()
                    window.updater.check()
                    deadline = time.monotonic() + 30
                    while window.updater.busy and time.monotonic() < deadline:
                        app.processEvents()
                        time.sleep(0.005)
                    if window.updater.busy or errors:
                        raise RuntimeError(f"Update fixture failed: {errors}")
                    sample(f"update_check_{attempt}", began)
            finally:
                update_process.worker_command = original_command
            # Accelerate only the isolated probe's idle grace period. Compare
            # these stages on the same runner before/after UI memory changes.
            if hasattr(window, "background_timer"):
                window.background_timer.setInterval(20)
            began = time.perf_counter()
            window.close()
            deadline = time.monotonic() + 0.1
            while time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            sample("window_hidden", began)
            metrics["window_hidden.rendered_items"] = management.list_widget.count()
            began = time.perf_counter()
            window.reveal()
            app.processEvents()
            sample("window_restored", began)
            if management.list_widget.count() != len(controller.messages.messages):
                raise RuntimeError("Hidden-window message list did not restore")
            result["tls_not_loaded_in_gui"] = all(name not in sys.modules for name in (
                "ssl", "truststore", "valorant_toxic_tamer.updater"))
        finally:
            app.aboutToQuit.disconnect(controller.cleanup)
            controller.cleanup()
            window.hide()
            window.deleteLater()
            controller.tray.deleteLater()
            app.processEvents()
    result["passed"] = result["tls_not_loaded_in_gui"]
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["passed"] else 1

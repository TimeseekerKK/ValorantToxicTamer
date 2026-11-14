"""Dispatch a network worker before loading any desktop UI modules."""
import sys


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--migrate-data":
        from .data_migration import run
        return run(sys.argv[2], sys.argv[3])
    if len(sys.argv) == 3 and sys.argv[1] == "--performance-check":
        import time
        started = time.perf_counter()
        from .performance_check import run
        return run(sys.argv[2], started)
    if len(sys.argv) == 3 and sys.argv[1] == "--performance-update-worker":
        from .performance_check import fixture_update_worker
        return fixture_update_worker(sys.argv[2])
    if len(sys.argv) == 4 and sys.argv[1] == "--check-update-worker":
        from .update_process import check_worker
        return check_worker(sys.argv[2], sys.argv[3])
    if len(sys.argv) == 3 and sys.argv[1] == "--download-update-worker":
        from .update_process import download_worker
        return download_worker(sys.argv[2])
    from .app import main as application_main
    return application_main()

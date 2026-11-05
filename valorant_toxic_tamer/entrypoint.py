"""Dispatch a network worker before loading any desktop UI modules."""
import sys


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--check-update-worker":
        from .update_process import check_worker
        return check_worker(sys.argv[2], sys.argv[3])
    from .app import main as application_main
    return application_main()

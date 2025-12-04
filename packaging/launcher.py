"""
PyInstaller-friendly launcher that starts the SelfObserver desktop watcher
and the Flask dashboard, then opens the UI in the default browser.

When built with PyInstaller, this entrypoint keeps paths stable by switching
into the project root (whether running from source or from a temporary
_pyibootstrap directory) so relative assets like logs, UI templates, and
config files resolve correctly.
"""
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Detect where the app is running from. PyInstaller sets sys._MEIPASS to the
# temporary extraction directory; otherwise fall back to the repository root.
BASE_PATH = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
PROJECT_ROOT = (BASE_PATH if (BASE_PATH / "ui").exists() else BASE_PATH.parent).resolve()

# Ensure imports work from the bundled root and set cwd for relative assets
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))


def run_dashboard():
    """Start the Flask UI server."""
    from ui.server import app

    app.run(host="127.0.0.1", port=5010, use_reloader=False)


def run_watcher():
    """Start the SelfObserver watcher loop + daily report scheduler."""
    import self_observer

    threading.Thread(target=self_observer.schedule_daily_report, daemon=True).start()
    self_observer.main()


def main():
    watcher = threading.Thread(target=run_watcher, daemon=True)
    watcher.start()

    server = threading.Thread(target=run_dashboard, daemon=True)
    server.start()

    # Give the server a moment to bind, then open the UI
    time.sleep(1)
    webbrowser.open("http://127.0.0.1:5010")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

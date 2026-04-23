"""
main.py — Entry point for the YouTube Downloader desktop app.

Starts Flask in a background thread and opens a native window via pywebview.
The existing Flask routes/HTML/CSS are reused without any changes.
"""

import sys
import os
import time
import threading
import socket
import logging

# ── Silence Flask's startup banner when running as a packaged app ─────────────
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

# ── PyInstaller resource path helper ──────────────────────────────────────────
def resource_path(relative: str) -> str:
    """Return the absolute path to a bundled resource (works in dev & .exe)."""
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, relative)


# ── Patch Flask template/static directories for PyInstaller ──────────────────
os.environ.setdefault("FLASK_TEMPLATE_FOLDER", resource_path("templates"))
os.environ.setdefault("FLASK_DOWNLOAD_DIR",    resource_path("downloads"))

# Import Flask app AFTER setting env vars so it picks up the correct paths
from app import app as flask_app  # noqa: E402


# ── Find a free port (avoids conflicts if the user has something on 5000) ─────
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = _free_port()


def _run_flask():
    flask_app.run(
        host="127.0.0.1",
        port=PORT,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


def _wait_for_flask(timeout: float = 10.0):
    """Block until Flask is accepting connections (or timeout)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import webview  # imported here so PyInstaller can find it

    # Start Flask in a daemon thread
    flask_thread = threading.Thread(target=_run_flask, daemon=True)
    flask_thread.start()

    # Wait until Flask is ready before opening the window
    if not _wait_for_flask():
        print("Erro: Flask não iniciou a tempo.", file=sys.stderr)
        sys.exit(1)

    # Create the native desktop window
    window = webview.create_window(
        title="YouTube Downloader",
        url=f"http://127.0.0.1:{PORT}",
        width=780,
        height=760,
        min_size=(540, 560),
        resizable=True,
        text_select=False,
        confirm_close=False,
    )

    # Start the GUI event loop (blocks until window is closed)
    webview.start(debug=False)

"""Fleet desktop app: engine server in a thread + native WebView2 window."""

import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine.server import make_server  # noqa: E402

PREFERRED_PORT = 8377


def main():
    try:
        import webview
    except ImportError:
        print("pywebview is not installed. Run: python -m pip install pywebview")
        print("Or use the browser UI instead: fleet dash")
        sys.exit(1)

    srv = None
    try:
        srv = make_server(PREFERRED_PORT)
        port = PREFERRED_PORT
    except OSError as e:
        if getattr(e, "winerror", None) != 10048:
            raise
        # fleet dash server already running - reuse it; confirm it answers
        port = PREFERRED_PORT
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                pass
        except OSError:
            srv = make_server(0)
            port = srv.server_address[1]
    if srv is not None:
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    window = webview.create_window(
        "Fleet", f"http://127.0.0.1:{port}/",
        width=1280, height=840, background_color="#1a1817")
    webview.start()
    if srv is not None:
        srv.shutdown()


if __name__ == "__main__":
    main()

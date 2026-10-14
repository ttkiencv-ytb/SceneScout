#!/usr/bin/env python3
"""Start SceneScout: a local server on 127.0.0.1 plus your browser."""
import socket
import sys
import threading
import webbrowser

import uvicorn

from scenescout import APP_NAME, __version__
from scenescout.server import app


def free_port(start=8765, end=8790):
    for port in range(start, end):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("No free port between 8765 and 8790. Close other SceneScout windows and try again.")


def main():
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    print(f"{APP_NAME} {__version__} is running at {url}")
    print("Keep this window open while you work. Close it to quit.")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()

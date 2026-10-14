#!/usr/bin/env python3
"""SceneScout desktop app: the same local server, shown in its own window.

Falls back to the default browser (with a small "running" window to quit) if the
native window cannot start, e.g. when WebView2 is missing on an old Windows install.
"""
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from scenescout import APP_NAME, __version__
from scenescout.config import data_dir
from scenescout.server import app


def free_port(start=8765, end=8800):
    for port in range(start, end):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("No free port")


def start_server(port):
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    for _ in range(100):  # wait up to ~10 s for the server
        try:
            urllib.request.urlopen(url + "api/meta", timeout=1)
            return url, server
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("SceneScout server did not start")


def browser_fallback(url):
    webbrowser.open(url)
    try:
        import tkinter as tk
        root = tk.Tk()
        root.title(APP_NAME)
        root.geometry("360x140")
        tk.Label(root, text=f"{APP_NAME} đang chạy trong trình duyệt.\nĐóng cửa sổ này để tắt app.", pady=16).pack()
        tk.Button(root, text="Mở lại trang SceneScout", command=lambda: webbrowser.open(url)).pack()
        root.mainloop()
    except Exception:
        while True:  # no GUI toolkit at all: keep serving until the process is killed
            time.sleep(3600)


def main():
    port = free_port()
    url, server = start_server(port)
    if os.environ.get("SCENESCOUT_NO_WINDOW") or "--browser" in sys.argv:
        print(f"{APP_NAME} {__version__} at {url}")
        return browser_fallback(url) if "--browser" in sys.argv else server_wait()
    try:
        import webview
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True  # Google / Envato / chat AI open in the normal browser
        webview.create_window(f"{APP_NAME} {__version__}", url, width=1440, height=920, min_size=(1000, 640),
                              text_select=True)
        storage = data_dir() / "webview"
        storage.mkdir(exist_ok=True)
        webview.start(private_mode=False, storage_path=str(storage))
    except Exception as e:  # pragma: no cover - depends on the OS
        print("Native window unavailable, using the browser:", e)
        browser_fallback(url)
    os._exit(0)


def server_wait():
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()

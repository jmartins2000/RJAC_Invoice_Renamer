"""The app window: a native window showing the HTML screens in src/web/ (WebKit on macOS,
Edge WebView2 on Windows), so text, icons and previews render crisply like the designs."""
import mimetypes
import os
import sys

import webview

from src.config import APP_CONFIG
from src.utils import get_resource_path
from src.webui.api import Api

WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"


def _windows_engine_missing():
    """Windows 10/11 normally include Microsoft Edge WebView2. If it's missing, say how to get it
    (pywebview would otherwise fall back to the old Internet Explorer engine, which can't run the app)."""
    import ctypes
    import webbrowser
    answer = ctypes.windll.user32.MessageBoxW(
        None, "This app needs Microsoft Edge WebView2, which is missing on this computer.\n\n"
              "Click OK to open Microsoft's download page, install it, then open the app again.",
        APP_CONFIG["NAME"], 0x31)  # OK/Cancel + warning icon
    if answer == 1:
        webbrowser.open(WEBVIEW2_URL)


def _free_port(preferred=42001):
    """pywebview always serves the page on port 42001 (so the page's saved state survives restarts).
    If that's taken — e.g. the app is already open, or another program uses it — the page server
    can't start and the window stays blank. Use 42001 when free, otherwise any free port."""
    import socket
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    return None


def create(api=None, debug=False):
    api = api or Api()
    index = get_resource_path(os.path.join("src", "web", "index.html"))
    window = webview.create_window(APP_CONFIG["NAME"], url=index, js_api=api, width=1120, height=760,
                                   min_size=(900, 600), background_color="#FFFFFF")
    api._window = window
    window.events.closed += api.review_close  # finish the run record if the window is closed mid-review
    return api, window


def start(func=None, args=None, debug=False):
    # The built-in server labels files by extension. On Windows Python reads those labels from the
    # registry, which often gets .js wrong; Edge WebView2 then refuses to run the page's modules.
    for ext in (".js", ".mjs"):
        mimetypes.add_type("text/javascript", ext)
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("font/woff2", ".woff2")
    gui = "edgechromium" if sys.platform == "win32" else None
    try:
        webview.start(func, args, debug=debug, http_server=True, private_mode=False, gui=gui,
                      http_port=_free_port())
    except Exception:
        if sys.platform == "win32":
            _windows_engine_missing()
        raise


def run(debug=False):
    create(debug=debug)
    start(debug=debug)


if __name__ == "__main__":
    run(debug="--debug" in sys.argv)

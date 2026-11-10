"""The app window: a native window showing the HTML screens in src/web/ (WebKit on macOS,
Edge WebView2 on Windows), so text, icons and previews render crisply like the designs."""
import os
import sys

import webview

from src.utils import get_resource_path
from src.webui.api import Api


def run(debug=False):
    api = Api()
    index = get_resource_path(os.path.join("src", "web", "index.html"))
    window = webview.create_window("RJAC Invoice Renamer", url=index, js_api=api,
                                   width=1120, height=760, min_size=(900, 600),
                                   background_color="#FFFFFF")
    api.window = window
    webview.start(debug=debug, http_server=True, private_mode=False,
                  storage_path=None, gui=None)


if __name__ == "__main__":
    run(debug="--debug" in sys.argv)

"""New interface (HTML screens in a native window). Run: python main_web.py [--debug]"""
import sys

import src  # noqa: F401  (safe console output on Windows)
from src.webui.app import run

if __name__ == "__main__":
    run(debug="--debug" in sys.argv)

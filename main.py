"""RJAC Invoice Renamer. Run: python main.py [--debug]   (--debug opens the web inspector)"""
import sys

import src  # noqa: F401  (safe console output on Windows)
from src.webui.app import run

if __name__ == "__main__":
    run(debug="--debug" in sys.argv)

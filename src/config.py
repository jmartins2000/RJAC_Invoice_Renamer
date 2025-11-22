import os
import sys
from dotenv import load_dotenv

# Load .env from the bundled location (works for both dev and PyInstaller)
if getattr(sys, 'frozen', False):
    # Running as PyInstaller bundle - .env is in _MEIPASS temp folder
    env_path = os.path.join(sys._MEIPASS, '.env')
else:
    # Running as script - .env is in project root
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')

load_dotenv(env_path)

# UI Colors
COLORS = {
    "DARK_GREEN": "#204e27",
    "LIGHT_GREEN": "#3d9d46",
    "WHITE": "#ffffff",
    "GRAY_TEXT": "#333333",
    "GRAY_SUBTEXT": "#666666"
}

# App Configuration
APP_CONFIG = {
    "NAME": "RJAC Invoice Renamer",
    "SIZE": "900x800",
    "ICON": "assets/RJAC-logo.png",
    "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY")
}

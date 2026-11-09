import os

from dotenv import load_dotenv

# Developer convenience only: a .env next to the source code may provide GEMINI_API_KEY.
# Packaged builds never include a .env; the key is entered in the app and kept in the
# app's data folder on this computer (see src/services/api_key.py).
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

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
}

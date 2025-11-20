import os
from dotenv import load_dotenv

load_dotenv()

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
    "SIZE": "900x750",
    "ICON": "assets/RJAC-logo.png",
    "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY")
}

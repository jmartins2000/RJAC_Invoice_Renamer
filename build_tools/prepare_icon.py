"""Generates the Windows .ico and macOS .icns icons from assets/RJAC-logo.png."""
import os
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = os.path.join(ROOT, "assets", "RJAC-logo.png")
img = Image.open(src).convert("RGBA")
img.save(os.path.join(ROOT, "assets", "RJAC-logo.ico"),
         sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
square = img.resize((1024, 1024), Image.Resampling.LANCZOS) if img.size != (1024, 1024) else img
square.save(os.path.join(ROOT, "assets", "RJAC-logo.icns"))
print("Icons written to assets/")

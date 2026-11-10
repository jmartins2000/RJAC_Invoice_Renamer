# PyInstaller spec — builds a folder app (Windows) or .app bundle (macOS).
# Run from the project root:  pyinstaller --noconfirm build_tools/rjac.spec
import os, sys, re
from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
VERSION = re.search(r'__version__ = "(.+?)"', open(os.path.join(ROOT, "src", "version.py")).read()).group(1)
NAME = "RJAC Invoice Renamer"

datas = [(os.path.join(ROOT, "assets"), "assets"),
         (os.path.join(ROOT, "src", "data"), os.path.join("src", "data")),
         (os.path.join(ROOT, "src", "web"), os.path.join("src", "web"))]  # the interface (HTML/CSS/JS, fonts)
binaries, hiddenimports = [], ["keyring.backends.Windows", "keyring.backends.macOS", "zxingcpp"]
pkgs = ["webview"]  # pywebview: its platform backends are imported dynamically
if sys.platform == "win32":
    pkgs += ["clr_loader", "pythonnet"]  # pywebview reaches Edge WebView2 through .NET (pythonnet)
for pkg in pkgs:
    d, b, h = collect_all(pkg); datas += d; binaries += b; hiddenimports += h
datas += copy_metadata("keyring") + copy_metadata("google-genai")

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["google.generativeai", "grpc", "matplotlib", "numpy", "pandas", "IPython", "tkinter", "customtkinter",
              "PyQt5", "PyQt6", "PySide2", "PySide6", "gi"],
)
pyz = PYZ(a.pure)

icon = os.path.join(ROOT, "assets", "RJAC-logo.icns" if sys.platform == "darwin" else "RJAC-logo.ico")
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False, icon=icon,
          upx=False, version=None)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{NAME}.app",
        icon=icon,
        bundle_identifier="com.jmartins.rjac-invoice-renamer",
        version=VERSION,
        info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": VERSION},
    )

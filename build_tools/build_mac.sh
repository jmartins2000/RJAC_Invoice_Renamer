#!/usr/bin/env bash
# Builds "RJAC Invoice Renamer.app" and a .dmg in dist/. Run from anywhere.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(python -c "import re;print(re.search(r'__version__ = \"(.+?)\"',open('src/version.py').read()).group(1))")
NAME="RJAC Invoice Renamer"

python build_tools/prepare_icon.py
rm -rf build "dist/$NAME" "dist/$NAME.app"
pyinstaller --noconfirm --distpath dist --workpath build build_tools/rjac.spec

# Ad-hoc sign so macOS treats the bundle as one consistent app.
codesign --force --deep --sign - "dist/$NAME.app"

DMG="dist/RJAC-Invoice-Renamer-$VERSION-mac.dmg"
STAGE=$(mktemp -d)
cp -R "dist/$NAME.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -volname "$NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
echo "Built: dist/$NAME.app and $DMG"

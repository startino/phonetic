#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
DIST="$ROOT/dist"

echo "Building macOS app..."
cd "$ROOT"
python -m PyInstaller packaging/phonetic.spec --distpath "$DIST" --workpath "$ROOT/build/pyinstaller" --clean

APP="$DIST/Phonetic.app"
if [ ! -d "$APP" ]; then
    echo "ERROR: $APP not found after build" >&2
    exit 1
fi

echo "Creating DMG..."
DMG="$DIST/Phonetic.dmg"
if command -v create-dmg &>/dev/null; then
    create-dmg \
        --volname "Phonetic" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --icon "Phonetic.app" 175 120 \
        --app-drop-link 425 120 \
        "$DMG" "$APP"
else
    hdiutil create -volname "Phonetic" -srcfolder "$APP" -ov -format UDZO "$DMG"
fi

echo "Done: $DMG"

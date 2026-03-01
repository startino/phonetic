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

# --- Ad-hoc code signing (inside-out) ---
# macOS Sequoia applies com.apple.provenance to apps in /Applications,
# which triggers dyld library validation. Signing every Mach-O binary
# with the same ad-hoc identity makes them compatible, and the
# disable-library-validation entitlement provides a fallback.
echo "Signing app bundle (inside-out)..."
ENTITLEMENTS="$SCRIPT_DIR/entitlements.plist"
SIGNED=0

# 1. Sign all Mach-O binaries inside Frameworks (libraries, extensions)
while IFS= read -r -d '' f; do
    if file "$f" | grep -q "Mach-O"; then
        codesign --force --sign - "$f" 2>/dev/null && SIGNED=$((SIGNED + 1)) || true
    fi
done < <(find "$APP/Contents/Frameworks" -type f -print0 2>/dev/null)

# 2. Sign any Mach-O binaries in Resources
while IFS= read -r -d '' f; do
    if file "$f" | grep -q "Mach-O"; then
        codesign --force --sign - "$f" 2>/dev/null && SIGNED=$((SIGNED + 1)) || true
    fi
done < <(find "$APP/Contents/Resources" -type f -print0 2>/dev/null)

# 3. Sign the main executable with entitlements
codesign --force --options runtime --sign - --entitlements "$ENTITLEMENTS" \
    "$APP/Contents/MacOS/phonetic"
SIGNED=$((SIGNED + 1))

# 4. Sign the app bundle
codesign --force --options runtime --sign - --entitlements "$ENTITLEMENTS" "$APP"
SIGNED=$((SIGNED + 1))

echo "Signed $SIGNED binaries."
codesign --verify --deep --strict "$APP" 2>&1 && echo "Signature verification: OK" \
    || echo "WARNING: Signature verification reported issues (may be expected for ad-hoc)"

# --- Create DMG ---
# No /Applications symlink — the app self-installs to ~/Applications on first
# launch because macOS Sequoia blocks ad-hoc signed apps in /Applications.
echo "Creating DMG..."
DMG="$DIST/Phonetic.dmg"

if command -v create-dmg &>/dev/null; then
    create-dmg \
        --volname "Phonetic" \
        --window-pos 200 120 \
        --window-size 400 300 \
        --icon-size 100 \
        --icon "Phonetic.app" 200 120 \
        "$DMG" "$APP"
else
    hdiutil create -volname "Phonetic" -srcfolder "$APP" -ov -format UDZO "$DMG"
fi
echo "Done: $DMG"

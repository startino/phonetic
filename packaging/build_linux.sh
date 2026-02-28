#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
DIST="$ROOT/dist"
VERSION="0.3.0"

echo "Building Linux binary..."
cd "$ROOT"
python -m PyInstaller packaging/phonetic.spec --distpath "$DIST" --workpath "$ROOT/build/pyinstaller" --clean

if [ ! -d "$DIST/phonetic" ]; then
    echo "ERROR: Build output not found" >&2
    exit 1
fi

# --- .deb package ---
echo "Creating .deb package..."
DEB_DIR="$DIST/deb"
rm -rf "$DEB_DIR"
mkdir -p "$DEB_DIR/DEBIAN"
mkdir -p "$DEB_DIR/opt/phonetic"
mkdir -p "$DEB_DIR/usr/share/applications"
mkdir -p "$DEB_DIR/usr/local/bin"

cp -r "$DIST/phonetic/"* "$DEB_DIR/opt/phonetic/"

cat > "$DEB_DIR/DEBIAN/control" <<EOF
Package: phonetic
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Depends: libportaudio2, libsndfile1, wl-clipboard | xclip, libnotify-bin
Maintainer: Startino <hello@startino.com>
Description: Hotkey-based speech-to-text via multimodal LLM
 Press a keybind to record, press again to stop — transcription
 is copied to your clipboard.
EOF

cat > "$DEB_DIR/usr/share/applications/phonetic.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Phonetic
Exec=/opt/phonetic/phonetic
Icon=/opt/phonetic/assets/icon.png
Comment=Speech-to-text via multimodal LLM
Categories=Utility;Audio;
StartupNotify=false
EOF

ln -sf /opt/phonetic/phonetic "$DEB_DIR/usr/local/bin/phonetic"

# Post-install script: launch Phonetic GUI so the first-run wizard appears
cat > "$DEB_DIR/DEBIAN/postinst" <<'EOF'
#!/bin/sh
# Launch Phonetic for the logged-in user so the first-run wizard appears
if [ "$1" = "configure" ]; then
    REAL_USER="${SUDO_USER:-$USER}"
    if [ "$REAL_USER" != "root" ] && command -v sudo >/dev/null; then
        sudo -u "$REAL_USER" sh -c \
          'DISPLAY="${DISPLAY:-:0}" nohup /opt/phonetic/phonetic >/dev/null 2>&1 &'
    fi
fi
EOF
chmod 755 "$DEB_DIR/DEBIAN/postinst"

dpkg-deb --build "$DEB_DIR" "$DIST/phonetic_${VERSION}_amd64.deb"
echo "Done: $DIST/phonetic_${VERSION}_amd64.deb"

# --- AppImage (if appimagetool available) ---
if command -v appimagetool &>/dev/null; then
    echo "Creating AppImage..."
    APPDIR="$DIST/Phonetic.AppDir"
    rm -rf "$APPDIR"
    mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/icons/hicolor/64x64/apps"

    cp -r "$DIST/phonetic/"* "$APPDIR/usr/bin/"
    cp "$ROOT/assets/icon.png" "$APPDIR/usr/share/icons/hicolor/64x64/apps/phonetic.png"
    cp "$ROOT/assets/icon.png" "$APPDIR/phonetic.png"

    cat > "$APPDIR/phonetic.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Phonetic
Exec=phonetic
Icon=phonetic
Categories=Utility;Audio;
EOF

    cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/phonetic" "$@"
EOF
    chmod +x "$APPDIR/AppRun"

    ARCH=x86_64 appimagetool "$APPDIR" "$DIST/Phonetic-${VERSION}-x86_64.AppImage"
    echo "Done: $DIST/Phonetic-${VERSION}-x86_64.AppImage"
else
    echo "appimagetool not found, skipping AppImage"
fi

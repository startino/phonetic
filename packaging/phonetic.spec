# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

block_cipher = None

root = Path(SPECPATH).parent

# Read version from pyproject.toml (single source of truth)
_version = "0.0.0"
for line in (root / "pyproject.toml").read_text().splitlines():
    if line.strip().startswith("version"):
        _version = line.split("=", 1)[1].strip().strip('"')
        break

a = Analysis(
    [str(root / 'main.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / 'assets'), 'assets'),
    ],
    hiddenimports=[
        'phonetic',
        'phonetic.__main__',
        'phonetic.app',
        'phonetic.config',
        'phonetic.constants',
        'phonetic.platform_utils',
        'phonetic.clipboard',
        'phonetic.recorder',
        'phonetic.transcribe',
        'phonetic.audio_detect',
        'phonetic.hotkeys',
        'phonetic.tray',
        'phonetic.notifications',
        'phonetic.autostart',
        'phonetic.update_check',
        'phonetic.ui',
        'phonetic.ui.settings',
        'phonetic.setup_prompt',
        *(['pystray._appindicator'] if sys.platform.startswith('linux') else []),
        *(['pystray._darwin'] if sys.platform == 'darwin' else []),
        *(['pystray._win32'] if sys.platform == 'win32' else []),
        *([
            'pynput.keyboard._xorg',
            'pynput.mouse._xorg',
            'pynput.keyboard._uinput',
            'pynput.mouse._uinput',
        ] if sys.platform.startswith('linux') else []),
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    module_collection_mode={
        'customtkinter': 'py',
    },
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='phonetic',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(root / 'assets' / 'icon.ico') if sys.platform == 'win32' else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='phonetic',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Phonetic.app',
        icon=str(root / 'assets' / 'icon.icns') if (root / 'assets' / 'icon.icns').exists() else None,
        bundle_identifier='com.startino.phonetic',
        info_plist={
            'LSUIElement': True,
            'CFBundleShortVersionString': _version,
            'CFBundleName': 'Phonetic',
            'NSMicrophoneUsageDescription': 'Phonetic needs microphone access to record audio for transcription.',
        },
    )

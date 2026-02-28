# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

block_cipher = None

root = Path(SPECPATH).parent

a = Analysis(
    [str(root / 'phonetic' / '__main__.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / 'assets'), 'assets'),
    ],
    hiddenimports=[
        'pystray._appindicator' if sys.platform.startswith('linux') else '',
        'pystray._darwin' if sys.platform == 'darwin' else '',
        'pystray._win32' if sys.platform == 'win32' else '',
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
        'customtkinter': 'collect_all',
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
            'CFBundleShortVersionString': '0.2.0',
            'CFBundleName': 'Phonetic',
        },
    )

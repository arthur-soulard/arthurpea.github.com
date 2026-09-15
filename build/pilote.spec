# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec : Pilote -> un seul Pilote.exe (onefile, sans console).

Usage :
    pyinstaller build/pilote.spec --clean --noconfirm
"""

import sys
from pathlib import Path

# Le .spec s'execute avec son repertoire courant = racine du projet
ROOT     = Path.cwd()
SRC      = ROOT / "src"
ASSETS   = ROOT / "assets"
ICON     = ASSETS / "icon.ico"


block_cipher = None


a = Analysis(
    [str(SRC / "app.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[
        # Embarque l'UI HTML et l'icone dans l'exe
        (str(SRC / "ui" / "index.html"), "ui"),
        # Script OCR (module Sante) : lu a l'execution via sys._MEIPASS
        (str(SRC / "ocr_win.ps1"),      "."),
        (str(ICON),                       "."),
    ],
    hiddenimports=[
        # pywebview backends Windows
        "webview.platforms.edgechromium",
        "webview.platforms.mshtml",
        "clr_loader",
        # win10toast deps
        "win10toast",
        # Pillow : icone recoloree a la volee (appicon.py, import paresseux)
        "PIL.Image",
        "PIL.ImageDraw",
        "PIL.ImageFont",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "unittest", "pydoc", "doctest",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Pilote",
    icon=str(ICON),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,           # pas de cmd noir
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=None,
    uac_admin=False,
)

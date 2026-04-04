# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

# ---------------------------------------------------------------------------
# Collect package data, binaries, and hidden imports
# ---------------------------------------------------------------------------
datas = []
binaries = []
hiddenimports = []

# Torch — heavy but needed for whisper
for pkg in ['torch']:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# PySide6 — only collect what we actually use (QtCore, QtWidgets, QtGui)
# collect_all('PySide6') is extremely slow and pulls in 3D, WebEngine, etc.
hiddenimports += [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'shiboken6',
]
datas += collect_data_files('PySide6', includes=['*.pyi', 'qt.conf'])

# Whisper — installed as openai-whisper, package name is 'whisper'
hiddenimports += collect_submodules('whisper')

# Project data files
datas += [
    ('fonts/Nulgl_case2-Regular.ttf', 'fonts'),
    ('assets/about_profile.png', 'assets'),
    ('assets/trik_klip.ico', 'assets'),
    ('.env.example', '.'),
]

# Lazy-loaded provider SDKs
hiddenimports += collect_submodules('anthropic')
hiddenimports += collect_submodules('openai')
hiddenimports += collect_submodules('google.genai')
hiddenimports += collect_submodules('google.generativeai')

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    ['gui_qt/app.py'],
    pathex=['C:/programming/streamclipper'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'tkinter', '_tkinter', 'customtkinter', 'tkinterdnd2'],
    noarchive=False,
)

# ---------------------------------------------------------------------------
# PYZ (bytecode archive)
# ---------------------------------------------------------------------------
pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# EXE
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Trik_Klip_Qt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    windowed=True,
    icon='assets/trik_klip.ico',
)

# ---------------------------------------------------------------------------
# COLLECT (onedir bundle)
# ---------------------------------------------------------------------------
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Trik_Klip_Qt',
)

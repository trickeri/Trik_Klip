# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

# ---------------------------------------------------------------------------
# Collect package data, binaries, and hidden imports for packages that ship
# assets, DLLs, or other non-Python files that PyInstaller won't find on its
# own.
# ---------------------------------------------------------------------------
datas = []
binaries = []
hiddenimports = []

for pkg in ['customtkinter', 'whisper', 'torch']:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Project data files
datas += [
    ('fonts/Nulgl_case2-Regular.ttf', 'fonts'),
    ('assets/about_profile.png', 'assets'),
    ('.env.example', '.'),
]

# Lazy-loaded provider SDKs (imported dynamically in providers.py)
hiddenimports += collect_submodules('anthropic')
hiddenimports += collect_submodules('openai')
hiddenimports += collect_submodules('google.genai')
hiddenimports += collect_submodules('google.generativeai')

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    ['gui.py'],
    pathex=['C:/programming/streamclipper'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='Trik_Klip',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    windowed=True,
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
    name='Trik_Klip',
)

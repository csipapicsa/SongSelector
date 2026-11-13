# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Windows one-file build. Run through scripts/build.ps1.
# All paths are relative to this file, so the repo can live anywhere.
import re
from pathlib import Path

ROOT = Path(SPECPATH).parent
PACKAGE = ROOT / 'src' / 'songselector'
VERSION = re.search(r"__version__ = '([^']+)'", (PACKAGE / '__init__.py').read_text()).group(1)

# Heavy libraries that may exist in the environment but are not used by the app.
EXCLUDES = ['matplotlib', 'scipy', 'IPython', 'pytest', 'numba', 'llvmlite', 'torch',
            'tensorflow', 'sklearn', 'jax', 'librosa', 'pyarrow', 'tkinter',
            'sympy', 'mpmath']  # onnxruntime needs sympy only for its offline tools

a = Analysis(
    [str(ROOT / 'packaging' / 'launcher.py')],
    pathex=[str(ROOT / 'src')],
    binaries=[],
    datas=[],
    hiddenimports=['mutagen', 'sqlcipher3', 'sqlcipher3.dbapi2'],  # sqlcipher3: Rekordbox's library
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f'SongSelector-{VERSION}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

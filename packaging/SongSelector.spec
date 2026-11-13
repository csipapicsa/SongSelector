# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Windows one-file build. Run through scripts/build.ps1.
# All paths are relative to this file, so the repo can live anywhere.
import re
from pathlib import Path

ROOT = Path(SPECPATH).parent
PACKAGE = ROOT / 'src' / 'songselector'
SPLASH_IMAGE = PACKAGE / 'ui' / 'splash.png'
VERSION = re.search(r"__version__ = '([^']+)'", (PACKAGE / '__init__.py').read_text()).group(1)

# Heavy libraries that may exist in the environment but are not used by the app.
EXCLUDES = ['matplotlib', 'scipy', 'IPython', 'pytest', 'numba', 'llvmlite', 'torch',
            'tensorflow', 'sklearn', 'jax', 'librosa', 'pyarrow', 'tkinter',
            'sympy', 'mpmath']  # onnxruntime needs sympy only for its offline tools

a = Analysis(
    [str(ROOT / 'packaging' / 'launcher.py')],
    pathex=[str(ROOT / 'src')],
    binaries=[],
    datas=[(str(SPLASH_IMAGE), 'songselector/ui')],  # for the app's own splash (ui/splash.py)
    hiddenimports=['mutagen', 'sqlcipher3', 'sqlcipher3.dbapi2'],  # sqlcipher3: Rekordbox's library
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# Splash screen shown by the exe itself from the first moment, while the one-file exe unpacks (several
# seconds, before any Python runs). The app replaces it with the same image (ui/splash.py) and closes it
# when the window is up. It needs Tcl/Tk in the build Python (GitHub's runners have it); without it the
# exe is built without this first splash, and only the app's own one shows.
from PyInstaller.utils.hooks.tcl_tk import tcltk_info

if tcltk_info.available:
    splash = Splash(str(SPLASH_IMAGE), binaries=a.binaries, datas=a.datas,
                    text_pos=(34, 212), text_size=10, text_color='#8c9096', text_default='Starting...',
                    minify_script=True, always_on_top=False)
    splash_parts = [splash, splash.binaries]
else:
    print('WARNING: this Python has no Tcl/Tk, so the exe is built without the startup splash screen.')
    splash_parts = []

exe = EXE(
    pyz,
    a.scripts,
    *splash_parts,
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

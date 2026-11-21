# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec. Windows: the one-file exe (scripts/build.ps1). Linux: a one-folder build that
# scripts/build_linux.sh packs into an AppImage.
# All paths are relative to this file, so the repo can live anywhere.
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
PACKAGE = ROOT / 'src' / 'songselector'
SPLASH_IMAGE = PACKAGE / 'ui' / 'splash.png'
ICON_IMAGE = PACKAGE / 'ui' / 'icon.png'
WINDOWS = sys.platform == 'win32'
VERSION = re.search(r"__version__ = '([^']+)'", (PACKAGE / '__init__.py').read_text()).group(1)

# Heavy libraries that may exist in the environment but are not used by the app.
EXCLUDES = ['matplotlib', 'scipy', 'IPython', 'pytest', 'numba', 'llvmlite', 'torch',
            'tensorflow', 'sklearn', 'jax', 'librosa', 'pyarrow', 'tkinter',
            'sympy', 'mpmath',  # onnxruntime needs sympy only for its offline tools
            'huggingface_hub', 'hf_xet', 'fsspec']  # tokenizers needs them only to download; the app loads files

a = Analysis(
    [str(ROOT / 'packaging' / 'launcher.py')],
    pathex=[str(ROOT / 'src')],
    binaries=[],
    datas=[(str(SPLASH_IMAGE), 'songselector/ui'),  # the app's own splash (ui/splash.py)
           (str(ICON_IMAGE), 'songselector/ui')],   # the window icon (app.py)
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
# exe is built without this first splash, and only the app's own one shows. Not on Linux: nothing unpacks there.
from PyInstaller.utils.hooks.tcl_tk import tcltk_info

if WINDOWS and tcltk_info.available:
    splash = Splash(str(SPLASH_IMAGE), binaries=a.binaries, datas=a.datas,
                    text_pos=(34, 212), text_size=10, text_color='#8c9096', text_default='Starting...',
                    minify_script=True, always_on_top=False)
    splash_parts = [splash, splash.binaries]
else:
    if WINDOWS:
        print('WARNING: this Python has no Tcl/Tk, so the exe is built without the startup splash screen.')
    splash_parts = []

if WINDOWS:
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
else:
    # Linux: one folder (dist/SongSelector/songselector plus _internal/). The AppImage around it is already a single
    # file and mounts instead of unpacking, so a one-file build inside it would only add an unpack at every start.
    # No UPX: compressed Qt libraries can fail to load.
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='songselector', debug=False,
              bootloader_ignore_signals=False, strip=False, upx=False, console=False)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='SongSelector')

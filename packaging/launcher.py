"""PyInstaller entry script.

Starts the app normally. With SONGSELECTOR_VERIFY_BUILD=1 it runs the packaged
self-check instead (used by scripts/verify_release.ps1).
"""
import multiprocessing
import os
import sys


def close_exe_splash():
    try:
        import pyi_splash  # only in an exe built with a splash screen
        pyi_splash.close()
    except Exception:
        pass


if __name__ == '__main__':
    # The embedding analysis process starts this same exe again; it must never show the startup splash.
    if '--multiprocessing-fork' in sys.argv:
        close_exe_splash()
    # Must run first: in the frozen exe, the embedding analysis process starts this
    # same exe, and freeze_support() turns that start into the worker instead of the app.
    multiprocessing.freeze_support()

    if os.environ.get('SONGSELECTOR_VERIFY_BUILD') == '1':
        close_exe_splash()
        from songselector.selfcheck import run
        sys.exit(run())

    from songselector.app import main
    sys.exit(main())

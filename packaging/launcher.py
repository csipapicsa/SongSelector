"""PyInstaller entry script.

Starts the app normally. With SONGSELECTOR_VERIFY_BUILD=1 it runs the packaged
self-check instead (used by scripts/verify_release.ps1).
"""
import multiprocessing
import os
import sys

if __name__ == '__main__':
    # Must run first: in the frozen exe, the embedding analysis process starts this
    # same exe, and freeze_support() turns that start into the worker instead of the app.
    multiprocessing.freeze_support()

    from songselector.app import main

    if os.environ.get('SONGSELECTOR_VERIFY_BUILD') == '1':
        from songselector.selfcheck import run
        sys.exit(run())
    sys.exit(main())

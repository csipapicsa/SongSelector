"""PyInstaller entry script.

Starts the app normally. With TRAKTOR_VERIFY_BUILD=1 it runs the packaged
self-check instead (used by scripts/verify_release.ps1).
"""
import os
import sys

from traktor_key_calculator.app import main

if os.environ.get('TRAKTOR_VERIFY_BUILD') == '1':
    from traktor_key_calculator.selfcheck import run
    sys.exit(run())
else:
    sys.exit(main())

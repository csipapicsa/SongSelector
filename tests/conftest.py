"""Test session setup: isolated app data directory and headless Qt.

This runs before any test module imports traktor_key_calculator, which matters
because config.APP_DATA_DIR is computed at import time.
"""
import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
# No default embedding model: test windows must not start analysing real tracks.
os.environ.setdefault('TRAKTOR_EMBEDDING_MODEL', 'none')
# Test windows must not read the Rekordbox library of the machine they run on.
os.environ.setdefault('TRAKTOR_REKORDBOX_LIBRARY', 'none')

_created_data_dir = None
if not os.environ.get('TRAKTOR_APP_DATA_DIR'):
    # resolve() expands Windows 8.3 short names (e.g. C:\Users\GERGOG~1). The tests
    # compare canonical path strings, which fail if the temp dir is in short form.
    _created_data_dir = Path(tempfile.mkdtemp(prefix='tkc-tests-')).resolve()
    os.environ['TRAKTOR_APP_DATA_DIR'] = str(_created_data_dir)


def pytest_sessionfinish(session, exitstatus):
    if _created_data_dir is not None:
        shutil.rmtree(_created_data_dir, ignore_errors=True)

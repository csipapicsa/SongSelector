import os
import json
import sys
from pathlib import Path

"""
Configuration and constants for the Traktor Key Calculator
"""
from PyQt5.QtGui import QColor

# Color mapping - Map integer values to colors (similar to Traktor)
COLOR_MAPPING_CATEGORY = {
    0: None,      # None/Default
    1: QColor(255, 0, 0),      # Red
    2: QColor(255, 165, 0),    # Orange
    3: QColor(255, 255, 0),    # Yellow
    4: QColor(0, 128, 0),      # Green
    5: QColor(0, 0, 255),      # Blue
    6: QColor(75, 0, 130),     # Indigo
    7: QColor(128, 0, 128),    # Violet/Magenta
    8: QColor(255, 192, 203),  # Pink
    9: QColor(165, 42, 42)     # Brown
}

OPEN_KEY_COLOR_MAPPING = {
    "1d": QColor(198, 106, 207),   # Purple
    "1m": QColor(221, 126, 202),
    "2d": QColor(149, 125, 216),   # Violet
    "2m": QColor(172, 145, 219),
    "3d": QColor(90, 141, 220),    # Blue
    "3m": QColor(123, 163, 222),
    "4d": QColor(68, 179, 228),    # Sky blue
    "4m": QColor(102, 191, 227),
    "5d": QColor(83, 204, 202),    # Turquoise
    "5m": QColor(107, 217, 196),
    "6d": QColor(92, 204, 147),    # Teal green
    "6m": QColor(121, 216, 153),
    "7d": QColor(115, 204, 83),    # Green
    "7m": QColor(146, 216, 108),
    "8d": QColor(169, 204, 83),    # Yellow-green
    "8m": QColor(194, 216, 108),
    "9d": QColor(222, 204, 83),    # Yellow
    "9m": QColor(233, 216, 108),
    "10d": QColor(245, 170, 83),   # Orange
    "10m": QColor(250, 189, 114),
    "11d": QColor(245, 122, 83),   # Red-orange
    "11m": QColor(250, 146, 114),
    "12d": QColor(230, 83, 83),    # Red
    "12m": QColor(245, 114, 114),
}

CAMELOT_KEY_TO_OPEN_KEY = {"1b": "6d", 
                    "1a": "6m", 
                    "2b": "7d", 
                    "2a": "7m",
                    "3b": "8d", 
                    "3a": "8m", 
                    "4b": "9d", 
                    "4a": "9m", 
                    "5b": "10d", 
                    "5a": "10m", 
                    "6b": "11d", 
                    "6a": "11m",
                    "7a": "12m",
                    "7b": "12d",
                    "8a": "1m",
                    "8b": "1d",
                    "9a": "2m",
                    "9b": "2d",
                    "10a": "3m",
                    "10b": "3d",
                    "11a": "4m",
                    "11b": "4d",
                    "12a": "5m",
                    "12b": "5d",
                    "0": "0"}

OPEN_KEY_TO_CAMELOT_KEY = {v: k for k, v in CAMELOT_KEY_TO_OPEN_KEY.items()}

AUDIO_EXTENSIONS = ["mp3", "wav", "flac"]

# config.py
from dataclasses import dataclass
from typing import Optional
@dataclass
class AudioMetadata:
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    genre: Optional[str] = None
    comment: Optional[str] = None
    bpm: Optional[str] = None
    key: Optional[str] = None
    rating: Optional[str] = None
    error: Optional[str] = None
    color: Optional[str] = None # color is not saved into the metadata at all

# Default application settings
DEFAULT_BPM = 128.0
WINDOW_SIZE = (1400, 800)
MIN_BPM = 70
MAX_BPM = 200


# Read-only files shipped with the app (bundled into the exe by PyInstaller).
PACKAGE_DATA_DIR = Path(__file__).resolve().parent / 'data'
DEFAULT_LIBRARY_CSV = PACKAGE_DATA_DIR / 'music_test.csv'


def _default_app_data_dir():
    """Where settings and imported tracks are stored.

    Priority: TRAKTOR_APP_DATA_DIR env var, then the folder of the frozen exe,
    then <repo>/.appdata when running from a source checkout.
    """
    if os.environ.get('TRAKTOR_APP_DATA_DIR'):
        return Path(os.environ['TRAKTOR_APP_DATA_DIR'])
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    repo_root = Path(__file__).resolve().parents[2]
    if (repo_root / 'pyproject.toml').is_file():
        return repo_root / '.appdata'
    return Path.home() / '.traktor_key_calculator'


APP_DATA_DIR = _default_app_data_dir()
SETTINGS_FILE = str(APP_DATA_DIR / 'SpotNextTrack_settings.json')

HEADER_LABELS = [
    "Artist", "Title", "Original BPM", "Original Key", "New Key",
    "Camelot Key New", "Open Key New", "Path", "Comment", "Genre", "Color"
]

HEADER_INDEX = {
    "Artist": 0,
    "Title": 1,
    "Original BPM": 2,
    "Original Key": 3,
    "New Key": 4,
    "Camelot Key New": 5,
    "Open Key New": 6,
    "Path": 7,
    "Comment": 8,
    "Genre": 9,
    "Color": 10
}

HEADER_LABELS += ['Album', 'Rating']
HEADER_INDEX.update({'Album': len(HEADER_LABELS) - 2, 'Rating': len(HEADER_LABELS) - 1})
COLOR_COLUMN_INDEX = HEADER_INDEX.get("Color", 10)

test = 100

SETTINGS_DEFAULT = {
    "Visible column left": HEADER_LABELS,
    "Visible column right": HEADER_LABELS,
    "Search columns": HEADER_LABELS,
    "Master Tempo": 120
}


def init_settings():
    """Create default settings file if not exists"""
    try:
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "w") as f:
                json.dump(SETTINGS_DEFAULT, f, indent=4)
        else:
            pass
        return True, ""
    except Exception as e:
        return False, e


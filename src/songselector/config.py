"""
Configuration and constants for SongSelector
"""
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from PyQt5.QtGui import QColor

from songselector.env import getenv

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


@dataclass
class AudioMetadata:
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    genre: str | None = None
    comment: str | None = None
    bpm: str | None = None
    key: str | None = None
    rating: str | None = None
    error: str | None = None
    color: str | None = None # color is not saved into the metadata at all

# Default application settings
DEFAULT_BPM = 128.0
WINDOW_SIZE = (1400, 800)
MIN_BPM = 70
MAX_BPM = 200


def _default_app_data_dir():
    """Where settings and imported tracks are stored.

    Priority: SONGSELECTOR_APP_DATA_DIR env var, then the folder of the frozen exe,
    then <repo>/.appdata when running from a source checkout, then ~/.songselector
    (~/.traktor_key_calculator if only that one exists, from before the rename).
    """
    if getenv('APP_DATA_DIR'):
        return Path(getenv('APP_DATA_DIR'))
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    repo_root = Path(__file__).resolve().parents[2]
    if (repo_root / 'pyproject.toml').is_file():
        return repo_root / '.appdata'
    current, legacy = Path.home() / '.songselector', Path.home() / '.traktor_key_calculator'
    return legacy if legacy.is_dir() and not current.exists() else current


APP_DATA_DIR = _default_app_data_dir()

# Embedding model used unless one is chosen in the app (Analysis menu) or placed in
# <data folder>\models\cnn14.onnx: where the developer keeps the model. Skipped when the file is absent.
# SONGSELECTOR_EMBEDDING_MODEL overrides it; "none" means no default (used by tests and verification).
DEFAULT_EMBEDDING_MODEL = getenv('EMBEDDING_MODEL', r'E:\GITHUB_E\MusicFindBoundaries\cnn14.onnx')
if DEFAULT_EMBEDDING_MODEL.strip().lower() in ('', 'none'):
    DEFAULT_EMBEDDING_MODEL = None
SETTINGS_FILE = str(APP_DATA_DIR / 'SongSelector_settings.json')
# The settings file's name before 1.1. init_settings() moves it to SETTINGS_FILE once.
LEGACY_SETTINGS_FILE = str(APP_DATA_DIR / 'SpotNextTrack_settings.json')

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

# The app's own rating and color, edited in the app and stored in library.sqlite.
# "Rating" and "Color" stay the values read from file tags / the Traktor collection.
SS_RATING_COLUMN = 'Rating - Song Selector'
SS_COLOR_COLUMN = 'Color - Song Selector'
HEADER_LABELS += [SS_RATING_COLUMN, SS_COLOR_COLUMN]
HEADER_INDEX.update({SS_RATING_COLUMN: len(HEADER_LABELS) - 2, SS_COLOR_COLUMN: len(HEADER_LABELS) - 1})

# Track fields: searchable, usable in Complex Search and on the map.
FIELD_LABELS = list(HEADER_LABELS)
# Position in the playlist ("1", "2", ...): the Playlist tab, and the List view while it
# shows a saved playlist. Not a track field. Shown as the first column.
POSITION_COLUMN = '#'
HEADER_LABELS += [POSITION_COLUMN]
HEADER_INDEX[POSITION_COLUMN] = len(HEADER_LABELS) - 1
# The track's group on the similarity map (1 = largest), with the map's grouping method; empty
# when grouping is off or the track is not analysed / in no group. Numbers change when the
# tracks are grouped again, so this is not a track field either.
GROUP_COLUMN = 'Group'
HEADER_LABELS += [GROUP_COLUMN]
HEADER_INDEX[GROUP_COLUMN] = len(HEADER_LABELS) - 1

SETTINGS_DEFAULT = {
    "Visible column left": HEADER_LABELS,
    "Visible column right": HEADER_LABELS,
    "Search columns": FIELD_LABELS,
    "Master Tempo": 120
}


def migrate_legacy_settings(settings_file=None, legacy_file=None):
    """Move the settings of a pre-1.1 install to the new file name, once.

    The old file is renamed to <name>.bak rather than deleted: it stays as a backup, and it is no
    longer found here, so resetting the settings later does not bring the old ones back.
    Returns True if a file was migrated.
    """
    settings_file = Path(settings_file or SETTINGS_FILE)
    legacy_file = Path(legacy_file or LEGACY_SETTINGS_FILE)
    if settings_file.exists() or not legacy_file.is_file():
        return False
    shutil.copy2(legacy_file, settings_file)
    os.replace(legacy_file, legacy_file.with_name(legacy_file.name + '.bak'))
    return True


def init_settings():
    """Create the settings file with defaults if it does not exist (after migrating an old one)."""
    try:
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        migrate_legacy_settings()
        if not os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "w") as f:
                json.dump(SETTINGS_DEFAULT, f, indent=4)
        return True, ""
    except Exception as e:
        return False, e


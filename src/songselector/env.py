"""Environment variables the app reads.

They are named SONGSELECTOR_<NAME>. Before the rename to SongSelector they were TRAKTOR_<NAME>;
those old names are still read as a fallback for one release, so existing setups keep working.

No imports beyond the standard library: the embedding worker process imports this too.
"""
import os

PREFIX = 'SONGSELECTOR_'
LEGACY_PREFIX = 'TRAKTOR_'  # until 1.1; remove the fallback in the release after


def getenv(name, default=None):
    """SONGSELECTOR_<name>, else the legacy TRAKTOR_<name>, else default."""
    value = os.environ.get(PREFIX + name)
    if value is None:
        value = os.environ.get(LEGACY_PREFIX + name)
    return default if value is None else value

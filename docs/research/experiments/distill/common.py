"""Shared pieces of the AllMusicCaps distillation experiments (see README.md in this folder).

Paths, the teacher's input contract, and the app's own decoding and windowing, so a student sees exactly the
windows that the teacher vectors in the app's cache (dist/embeddings-amc-clap.sqlite) were made from.
"""
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / 'src'))

from songselector.core import embeddings as app_embeddings  # noqa: E402
from songselector.core.embedding_models import AMC_CLAP  # noqa: E402

APP_DATA = REPO / 'dist'                              # the live install: library, embedding caches, models/
TEACHER_ONNX = APP_DATA / 'models' / AMC_CLAP.audio_file
TEACHER_CACHE = APP_DATA / AMC_CLAP.store_file
WORK = REPO / '.research_cache' / 'distill'           # gitignored: student ONNX files, feature cache, MLflow store
TEACHER_SNAPSHOT = WORK / 'snapshot' / AMC_CLAP.store_file
RESULTS = REPO / 'docs' / 'research' / 'experiments' / 'results'

RATE = AMC_CLAP.sample_rate        # 24 kHz
WINDOW = AMC_CLAP.chunk_samples    # 10 s = 240,000 samples
DIM = AMC_CLAP.dim                 # 512
SAMPLED_WINDOWS = 6                # windows per track when sampling (2026-11-22: as good as every window)


def decode(path):
    """Mono float32 at 24 kHz, decoded exactly as the app's analysis does (libsndfile + soxr, FFmpeg fallback)."""
    return app_embeddings.load_audio_rates(path, [RATE])[RATE]


def windows_of(audio):
    """(n, 240000): non-overlapping 10 s windows from the start, the last one zero-padded, as the app embeds."""
    return app_embeddings.split_chunks(audio, WINDOW)


def sampled_indices(count, k=SAMPLED_WINDOWS):
    """Indices of k evenly spaced windows, at (i + 0.5) / k of the track (the 2026-11-22 sampling test)."""
    if count <= k:
        return np.arange(count)
    return np.array([int((i + 0.5) * count / k) for i in range(k)])


def connect_ro(path):
    """Read-only connection: cannot change the file."""
    return sqlite3.connect(f'file:{Path(path).as_posix()}?mode=ro', uri=True)


def teacher_cache():
    """A frozen copy of the app's AllMusicCaps cache, made on first use with SQLite's backup API (safe while the app
    runs). Experiments read the copy, never the live file (docs/research/README.md), and the copy keeps the
    training data fixed while the app goes on analysing new tracks. Delete it to take a new snapshot."""
    if not TEACHER_SNAPSHOT.is_file():
        TEACHER_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        partial = TEACHER_SNAPSHOT.with_suffix('.partial')
        with closing(connect_ro(TEACHER_CACHE)) as source, closing(sqlite3.connect(partial)) as target:
            source.backup(target)
        partial.replace(TEACHER_SNAPSHOT)
    return TEACHER_SNAPSHOT


def teacher_tracks(min_windows=1, max_windows=10**9):
    """[(path, windows)] of every track the app embedded with AllMusicCaps, sorted by path."""
    with closing(connect_ro(teacher_cache())) as connection:
        rows = connection.execute(
            'SELECT path_key, frames FROM embeddings WHERE error IS NULL AND frames BETWEEN ? AND ? '
            'ORDER BY path_key', (min_windows, max_windows)).fetchall()
    return [(Path(path_key), frames) for path_key, frames in rows]


def teacher_vectors(path):
    """(n, 512) float32 cached teacher vectors of one track, one per 10 s window, as the app stored them."""
    with closing(connect_ro(teacher_cache())) as connection:
        frames, dim, encoding, blob = connection.execute(
            'SELECT frames, dim, encoding, data FROM embeddings WHERE path_key = ?', (str(path),)).fetchone()
    if encoding != app_embeddings.ENCODING:
        raise ValueError(f'unexpected encoding {encoding}')
    return app_embeddings.decode(blob, frames, dim).astype(np.float32)

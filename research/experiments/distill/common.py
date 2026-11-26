"""Shared pieces of the AllMusicCaps distillation experiments (see README.md in this folder).

Paths, the teacher's input contract, and the app's own decoding and windowing, so a student sees exactly the
windows that the teacher vectors in the app's cache (dist/embeddings-amc-clap.sqlite) were made from.
"""
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'src'))

from songselector.core import embeddings as app_embeddings  # noqa: E402
from songselector.core.embedding_models import AMC_CLAP  # noqa: E402

APP_DATA = REPO / 'dist'                              # the live install: library, embedding caches, models/
TEACHER_ONNX = APP_DATA / 'models' / AMC_CLAP.audio_file
TEACHER_CACHE = APP_DATA / AMC_CLAP.store_file
WORK = REPO / '.research_cache' / 'distill'           # gitignored: student ONNX files, feature cache, MLflow store
DATA = WORK / 'data'                                  # Phase 1 feature cache (prepare_data.py)
RESULTS = REPO / 'research' / 'results'

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


def snapshot(source):
    """A frozen copy of one of the app's SQLite files in WORK/snapshot, made on first use with SQLite's backup API
    (safe while the app runs). Experiments read the copy, never the live file (docs/research/README.md), and the
    copy keeps the data fixed while the app goes on analysing new tracks. Delete it to take a new snapshot."""
    copy = WORK / 'snapshot' / Path(source).name
    if not copy.is_file():
        copy.parent.mkdir(parents=True, exist_ok=True)
        partial = copy.with_suffix('.partial')
        with closing(connect_ro(source)) as original, closing(sqlite3.connect(partial)) as target:
            original.backup(target)
        partial.replace(copy)
    return copy


def teacher_cache():
    """The snapshot of the app's AllMusicCaps cache (teacher vectors of every window of 3,380 tracks)."""
    return snapshot(TEACHER_CACHE)


def library():
    """The snapshot of the app's library (artist, genre, file path of every track)."""
    return snapshot(APP_DATA / 'library.sqlite')


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


# ---- Experiment tracking -----------------------------------------------------------------------------------------

MLFLOW_DB = WORK / 'mlflow.db'
MLFLOW_ARTIFACTS = WORK / 'mlartifacts'


def mlflow_experiment(name):
    """MLflow pointed at the local store and experiment `name` selected (created on first use). Runs go to a SQLite
    file, artifacts to files next to it, both in the git-ignored WORK folder. To browse, from the repo root:

        .research_cache\\venv-distill\\Scripts\\mlflow ui --backend-store-uri sqlite:///.research_cache/distill/mlflow.db
    """
    import os
    os.environ.setdefault('MLFLOW_DISABLE_AGENT_HINT', '1')   # a hint for coding agents printed on every import
    import mlflow
    WORK.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(f'sqlite:///{MLFLOW_DB.as_posix()}')
    if mlflow.get_experiment_by_name(name) is None:
        mlflow.create_experiment(name, artifact_location=(MLFLOW_ARTIFACTS / name).as_uri())
    mlflow.set_experiment(name)
    return mlflow


CODE_PATHS = ('research/experiments/distill/*.py', 'src/songselector/*.py')   # git pathspecs: * crosses folders


def log_code_state(mlflow):
    """Record in the active run exactly which code and packages it used, so it can be reproduced later.

    mlflow.source.git.commit (set by MLflow) is only the commit the work started from; a run started on edited code
    would point at code without those edits. So: tag code_commit and code_dirty (do the research code or the app
    code it imports differ from that commit?), and if they do, log the difference (code/uncommitted.diff) and any
    new, untracked files (code/untracked/). Also the installed packages (environment/packages.txt). Checkout of
    code_commit + applying the diff gives the run's code; the packages file gives its environment."""
    import importlib.metadata
    import platform
    import subprocess

    def git(*args):
        return subprocess.run(['git', *args], cwd=REPO, capture_output=True, text=True, check=True).stdout

    diff = git('diff', 'HEAD', '--', *CODE_PATHS)
    untracked = git('ls-files', '--others', '--exclude-standard', '--', *CODE_PATHS).split()
    mlflow.set_tags({'code_commit': git('rev-parse', 'HEAD').strip(),
                     'code_dirty': str(bool(diff or untracked)).lower()})
    if diff:
        mlflow.log_text(diff, 'code/uncommitted.diff')
    for name in untracked:
        mlflow.log_artifact(str(REPO / name), 'code/untracked')
    packages = sorted(f"{dist.metadata['Name']}=={dist.version}" for dist in importlib.metadata.distributions())
    mlflow.log_text(f'python {platform.python_version()} on {platform.platform()}\n' + '\n'.join(packages) + '\n',
                    'environment/packages.txt')

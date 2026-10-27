"""Audio embeddings: PANNs CNN14, one 2048-value vector per 5 seconds of audio.

Same model and preprocessing as the DJ mix segmentation project
(see docs/research/audio_embeddings.md): mono, 32 kHz, 5 s chunks, the last
chunk zero-padded. Decoding uses soundfile + soxr instead of librosa, and the
model runs through onnxruntime instead of PyTorch; both give identical
embeddings to the original pipeline (verified on a real track).

Embeddings are a cache that can be recomputed, so they live in their own SQLite
file (embeddings.sqlite) instead of library.sqlite, which holds user data.

Analysis runs in a separate process (run_analysis) that never loads Qt:
PyQt5 ships an older MSVC runtime that makes onnxruntime crash when it loads
after Qt, and a crashing decoder on a broken file must not take the app down.
This module must therefore not import PyQt5 or traktor_key_calculator.config.
"""
import os
import queue
import sqlite3
import zlib
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

MODEL_ID = 'panns-cnn14-mAP0.431'
MODEL_FILE_NAME = 'cnn14.onnx'
SAMPLE_RATE = 32000
CHUNK_SECONDS = 5
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_SECONDS
EMBEDDING_DIM = 2048
# float16 like the segmentation project; zlib is lossless and shrinks the data to
# about 21% because ~87% of CNN14 embedding values are exactly zero (ReLU output).
ENCODING = 'float16-zlib'
_DECODE_BLOCK = 1 << 18  # frames per read, so a long file can be interrupted between blocks


class Cancelled(Exception):
    """Raised when analysis is stopped mid-track."""


def file_fingerprint(path):
    """(size, mtime_ns) of a file: cheap check whether an embedding is still current."""
    stat = os.stat(path)
    return stat.st_size, stat.st_mtime_ns


def load_audio(path, should_stop=lambda: False):
    """Decode to mono float32 at 32 kHz, matching librosa.load(path, sr=32000, mono=True)."""
    import soundfile
    import soxr
    blocks = []
    with soundfile.SoundFile(str(path)) as audio_file:
        sample_rate = audio_file.samplerate
        while True:
            if should_stop():
                raise Cancelled()
            block = audio_file.read(_DECODE_BLOCK, dtype='float32', always_2d=True)
            if not len(block):
                break
            blocks.append(block.mean(axis=1))
    mono = np.concatenate(blocks) if blocks else np.zeros(0, dtype=np.float32)
    if sample_rate != SAMPLE_RATE and len(mono):
        mono = soxr.resample(mono, sample_rate, SAMPLE_RATE, quality='HQ')
    return mono.astype(np.float32, copy=False)


def split_chunks(audio):
    """(n_chunks, CHUNK_SAMPLES) array; the last chunk is zero-padded."""
    count = max(1, -(-len(audio) // CHUNK_SAMPLES))
    padded = np.zeros(count * CHUNK_SAMPLES, dtype=np.float32)
    padded[:len(audio)] = audio
    return padded.reshape(count, CHUNK_SAMPLES)


def encode(matrix):
    return zlib.compress(np.ascontiguousarray(matrix, dtype=np.float16).tobytes(), 6)


def decode(blob, frames, dim=EMBEDDING_DIM):
    return np.frombuffer(zlib.decompress(blob), dtype=np.float16).reshape(frames, dim)


# Fastest first. Which ones exist depends on the installed package: onnxruntime (CPU),
# onnxruntime-gpu (CUDA, needs CUDA 12 + cuDNN 9 DLLs) or onnxruntime-directml (any DX12 GPU).
PREFERRED_PROVIDERS = ('CUDAExecutionProvider', 'DmlExecutionProvider', 'CPUExecutionProvider')
GPU_BATCH_SIZE = 16            # 16 x 5 s chunks; fits easily in 4 GB of video memory
# Folder with CUDA 12 / cuDNN 9 DLLs to use, e.g. ...\site-packages\torch\lib of a CUDA PyTorch.
CUDA_DLL_DIR_VARIABLE = 'TRAKTOR_CUDA_DLL_DIR'


class Cnn14Embedder:
    """CNN14 through onnxruntime, on the GPU when available. Loading the model takes a few seconds."""

    def __init__(self, model_path, threads=None):
        import onnxruntime
        if 'CUDAExecutionProvider' in onnxruntime.get_available_providers() and hasattr(onnxruntime, 'preload_dlls'):
            try:  # CUDA 12 / cuDNN 9 DLLs: from TRAKTOR_CUDA_DLL_DIR, else the nvidia-* pip packages
                onnxruntime.preload_dlls(directory=os.environ.get(CUDA_DLL_DIR_VARIABLE) or None)
            except Exception:
                pass
        options = onnxruntime.SessionOptions()
        # Leave half the CPU to the UI and the rest of the system.
        options.intra_op_num_threads = threads or max(1, (os.cpu_count() or 2) // 2)
        options.inter_op_num_threads = 1
        available = onnxruntime.get_available_providers()
        providers = [name for name in PREFERRED_PROVIDERS if name in available] or ['CPUExecutionProvider']
        try:
            self.session = onnxruntime.InferenceSession(str(model_path), options, providers=providers)
        except Exception:
            if providers == ['CPUExecutionProvider']:
                raise
            # e.g. CUDA provider present but its DLLs are missing: fall back to the CPU
            self.session = onnxruntime.InferenceSession(str(model_path), options, providers=['CPUExecutionProvider'])
        self.provider = self.session.get_providers()[0]
        self.input_name = self.session.get_inputs()[0].name
        # Batching makes a GPU ~2.5x faster; on the CPU it gains nothing, and single
        # chunks let a pause take effect sooner.
        self.batch_size = 1 if self.provider == 'CPUExecutionProvider' else GPU_BATCH_SIZE

    def embed(self, audio, should_stop=lambda: False):
        """(n_chunks, 2048) float32 embeddings of mono 32 kHz audio."""
        chunks = split_chunks(audio)
        batches = []
        for start in range(0, len(chunks), self.batch_size):
            if should_stop():
                raise Cancelled()
            batches.append(self.session.run(['embedding'], {self.input_name: chunks[start:start + self.batch_size]})[0])
        return np.concatenate(batches)


class EmbeddingStore:
    """embeddings.sqlite: one row per track (path_key as in library.sqlite)."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS embeddings (
        path_key      TEXT PRIMARY KEY,
        model         TEXT NOT NULL,
        file_size     INTEGER NOT NULL,   -- fingerprint of the audio file when analysed
        file_mtime_ns INTEGER NOT NULL,
        sample_rate   INTEGER NOT NULL,
        chunk_seconds REAL NOT NULL,
        frames        INTEGER NOT NULL,   -- number of 5 s chunks; 0 when error is set
        dim           INTEGER NOT NULL,
        encoding      TEXT NOT NULL,
        data          BLOB,               -- encode(matrix); NULL when error is set
        error         TEXT,               -- why the file could not be analysed
        created_at    TEXT NOT NULL
    );
    """

    def __init__(self, path):
        self.path = Path(path)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # The UI reads while the background worker writes; WAL lets both proceed.
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute('PRAGMA journal_mode=WAL')
        connection.executescript(self._SCHEMA)
        return connection

    def fingerprints(self, model=MODEL_ID):
        """{path_key: (size, mtime_ns)} of stored results (embeddings and errors) for a model."""
        with closing(self._connect()) as connection:
            rows = connection.execute('SELECT path_key, file_size, file_mtime_ns FROM embeddings WHERE model = ?',
                                      (model,)).fetchall()
        return {key: (size, mtime) for key, size, mtime in rows}

    def save(self, path_key, fingerprint, matrix, model=MODEL_ID):
        self._write(path_key, fingerprint, model, len(matrix), encode(matrix), None)

    def save_error(self, path_key, fingerprint, error, model=MODEL_ID):
        self._write(path_key, fingerprint, model, 0, None, str(error)[:500])

    def _write(self, path_key, fingerprint, model, frames, data, error):
        with closing(self._connect()) as connection, connection:
            connection.execute('INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                               (path_key, model, fingerprint[0], fingerprint[1], SAMPLE_RATE, CHUNK_SECONDS,
                                frames, EMBEDDING_DIM, ENCODING, data, error,
                                datetime.now(timezone.utc).isoformat(timespec='seconds')))

    def load(self, path_key, model=MODEL_ID):
        """(frames, 2048) float16 array, or None if missing or failed."""
        with closing(self._connect()) as connection:
            row = connection.execute('SELECT frames, dim, data FROM embeddings WHERE path_key = ? AND model = ? '
                                     'AND data IS NOT NULL', (path_key, model)).fetchone()
        return decode(row[2], row[0], row[1]) if row else None

    def update_fingerprint(self, path_key, fingerprint):
        """After a tag-only edit the audio is unchanged: keep the embedding current."""
        with closing(self._connect()) as connection, connection:
            connection.execute('UPDATE embeddings SET file_size = ?, file_mtime_ns = ? WHERE path_key = ?',
                               (fingerprint[0], fingerprint[1], path_key))

    def counts(self, model=MODEL_ID):
        """(analysed, failed) number of tracks."""
        with closing(self._connect()) as connection:
            return connection.execute('SELECT COUNT(data), COUNT(error) FROM embeddings WHERE model = ?',
                                      (model,)).fetchone()


def _lower_process_priority():
    if os.name == 'nt':  # keep the UI and DJ software responsive while analysing
        import ctypes
        below_normal = 0x4000
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), below_normal)


def run_analysis(model_path, store_path, jobs, events, stop, embedder_factory=Cnn14Embedder):
    """Entry point of the analysis process.

    Reads (path_key, file_path) jobs from the `jobs` queue until `stop` is set and
    reports on `events`:
      ('ready', provider)        model loaded; provider e.g. CUDAExecutionProvider
      ('start', key, file name)  analysing a file (if the process dies now, this file caused it)
      ('done', key, status)      status: analysed | current | missing | failed | cancelled
      ('fatal', message)         cannot continue (e.g. broken model file)
    """
    _lower_process_priority()
    try:
        embedder = embedder_factory(model_path)
        store = EmbeddingStore(store_path)
        known = store.fingerprints()
    except Exception as error:
        events.put(('fatal', f'{type(error).__name__}: {error}'))
        return
    events.put(('ready', getattr(embedder, 'provider', 'CPUExecutionProvider')))
    while not stop.is_set():
        try:
            key, path = jobs.get(timeout=0.2)
        except queue.Empty:
            continue
        try:
            fingerprint = file_fingerprint(path)
        except OSError:
            events.put(('done', key, 'missing'))
            continue
        if known.get(key) == fingerprint:
            events.put(('done', key, 'current'))
            continue
        events.put(('start', key, Path(path).name))
        try:
            matrix = embedder.embed(load_audio(path, stop.is_set), stop.is_set)
            store.save(key, fingerprint, matrix)
            status = 'analysed'
        except Cancelled:
            events.put(('done', key, 'cancelled'))
            break
        except Exception as error:  # undecodable file: remember it, retry only if the file changes
            store.save_error(key, fingerprint, f'{type(error).__name__}: {error}')
            status = 'failed'
        known[key] = fingerprint
        events.put(('done', key, status))

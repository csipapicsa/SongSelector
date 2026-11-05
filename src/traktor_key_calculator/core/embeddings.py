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
from contextlib import closing, contextmanager
from datetime import UTC, datetime
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
PARTIAL_MIN_SECONDS = 10  # a file that stops decoding is still analysed if this much, and
PARTIAL_MIN_SHARE = 0.5   # this share of its length, could be read (see load_audio)
# Bump when a change could make earlier failures succeed: failed tracks are then tried again once.
_FAILURES_VERSION = 3  # 3: FFmpeg (PyAV) as a second decoder; 2: partial decoding


class Cancelled(Exception):
    """Raised when analysis is stopped mid-track."""


def file_fingerprint(path):
    """(size, mtime_ns) of a file: cheap check whether an embedding is still current."""
    stat = os.stat(path)
    return stat.st_size, stat.st_mtime_ns


def _enough(decoded_seconds, expected_seconds):
    """A file that stops decoding is still analysed if at least PARTIAL_MIN_SECONDS and
    PARTIAL_MIN_SHARE of its length could be read: the embedding is an average over the whole
    track, so a missing last stretch changes it very little."""
    return decoded_seconds >= max(PARTIAL_MIN_SECONDS, PARTIAL_MIN_SHARE * max(expected_seconds, 0))


def _read_soundfile(path, should_stop):
    """(mono float32 at 32 kHz, problem): problem is None, or the error that stopped libsndfile
    after enough was decoded. Raises if the file cannot be opened or too little was decoded."""
    import soundfile
    import soxr
    blocks, decoded, problem = [], 0, None
    with soundfile.SoundFile(str(path)) as audio_file:
        sample_rate = audio_file.samplerate
        expected = audio_file.frames  # an estimate for MP3; 0 when unknown
        try:
            while True:
                if should_stop():
                    raise Cancelled()
                block = audio_file.read(_DECODE_BLOCK, dtype='float32', always_2d=True)
                if not len(block):
                    break
                blocks.append(block.mean(axis=1))
                decoded += len(block)
        except Cancelled:
            raise
        except Exception as error:  # a bad frame, often near the end of an MP3
            if not _enough(decoded / sample_rate, expected / sample_rate):
                raise
            problem = error
    mono = np.concatenate(blocks) if blocks else np.zeros(0, dtype=np.float32)
    if sample_rate != SAMPLE_RATE and len(mono):
        mono = soxr.resample(mono, sample_rate, SAMPLE_RATE, quality='HQ')
    return mono.astype(np.float32, copy=False), problem


def _read_av(path, should_stop):
    """Mono float32 at 32 kHz decoded with FFmpeg (PyAV). It reads what libsndfile cannot: AAC
    (.m4a, .mp4) and MP3s with damaged frames, which FFmpeg skips and reads on past, as its own
    command line does. A file read without any damage is returned whatever its length; after damage
    it must pass _enough. Raises (ImportError if PyAV is missing) when too little could be decoded."""
    import av
    resampler = av.AudioResampler(format='fltp', rate=SAMPLE_RATE)  # keeps the channels; averaged below
    pieces, damaged = [], False
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        expected = container.duration / av.time_base if container.duration else 0
        try:
            for packet in container.demux(stream):
                if should_stop():
                    raise Cancelled()
                try:
                    frames = packet.decode()
                except av.error.FFmpegError:  # a damaged packet: skip it
                    damaged = True
                    continue
                for frame in frames:
                    pieces.extend(piece.to_ndarray().mean(axis=0) for piece in resampler.resample(frame))
            pieces.extend(piece.to_ndarray().mean(axis=0) for piece in resampler.resample(None))
        except av.error.FFmpegError:  # the file cannot be read on from here
            damaged = True
    audio = np.concatenate(pieces).astype(np.float32, copy=False) if pieces else np.zeros(0, dtype=np.float32)
    if not len(audio) or (damaged and not _enough(len(audio) / SAMPLE_RATE, expected)):
        raise ValueError(f'FFmpeg decoded only {len(audio) / SAMPLE_RATE:.0f} s of {expected:.0f} s')
    return audio


def load_audio(path, should_stop=lambda: False):
    """Decode to mono float32 at 32 kHz, matching librosa.load(path, sr=32000, mono=True).

    libsndfile decodes first (MP3, FLAC, WAV). If it cannot open the file (AAC) or stops at a
    damaged frame, FFmpeg is tried as well and the longer result is used; see _enough for how
    little may be missing. If neither decodes enough, libsndfile's error is raised.
    """
    candidates, problem = [], None
    try:
        audio, problem = _read_soundfile(path, should_stop)
        candidates.append(audio)
    except Cancelled:
        raise
    except Exception as error:
        problem = error
    if problem is not None:
        try:
            candidates.append(_read_av(path, should_stop))
        except Cancelled:
            raise
        except Exception:  # PyAV not installed, or FFmpeg cannot read the file either
            pass
    if not candidates:
        raise problem
    return max(candidates, key=len)


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


# Fastest first. Which ones exist depends on the installed package: onnxruntime-directml
# (default; any DirectX 12 GPU, plus CPU), onnxruntime-gpu (CUDA, needs CUDA 12 + cuDNN 9 DLLs)
# or onnxruntime (CPU only).
PREFERRED_PROVIDERS = ('CUDAExecutionProvider', 'DmlExecutionProvider', 'CPUExecutionProvider')
# 5 s chunks per model call, measured on a GTX 1650 Ti (4 GB), 6-minute track:
# CUDA batch 16: 0.58 s; DirectML batch 8: 0.58 s (batch 16: 4.2 s); CPU: 5.5 s at any batch
# size, so 1 there, which also lets a pause take effect sooner.
BATCH_SIZES = {'CUDAExecutionProvider': 16, 'DmlExecutionProvider': 8, 'CPUExecutionProvider': 1}
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
        available = onnxruntime.get_available_providers()
        providers = [name for name in PREFERRED_PROVIDERS if name in available] or ['CPUExecutionProvider']
        try:
            self.session = onnxruntime.InferenceSession(str(model_path), self._options(onnxruntime, threads),
                                                        providers=providers)
        except Exception:
            if providers == ['CPUExecutionProvider']:
                raise
            # e.g. CUDA DLLs missing or no DirectX 12 GPU: fall back to the CPU
            self.session = onnxruntime.InferenceSession(str(model_path), self._options(onnxruntime, threads),
                                                        providers=['CPUExecutionProvider'])
        self.provider = self.session.get_providers()[0]
        self.input_name = self.session.get_inputs()[0].name
        self.batch_size = BATCH_SIZES.get(self.provider, 1)

    @staticmethod
    def _options(onnxruntime, threads):
        options = onnxruntime.SessionOptions()
        # Leave half the CPU to the UI and the rest of the system.
        options.intra_op_num_threads = threads or max(1, (os.cpu_count() or 2) // 2)
        options.inter_op_num_threads = 1
        # Required by the DirectML provider; harmless for the others.
        options.enable_mem_pattern = False
        options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
        return options

    def embed(self, audio, should_stop=lambda: False):
        """(n_chunks, 2048) float32 embeddings of mono 32 kHz audio."""
        chunks = split_chunks(audio)
        count, size = len(chunks), self.batch_size
        if size > 1 and count % size:
            # Every call gets the same shape: GPU providers re-plan the model for each new
            # input shape. The zero padding is cut off again below.
            chunks = np.concatenate([chunks, np.zeros((size - count % size, CHUNK_SAMPLES), dtype=np.float32)])
        batches = []
        for start in range(0, len(chunks), size):
            if should_stop():
                raise Cancelled()
            batches.append(self.session.run(['embedding'], {self.input_name: chunks[start:start + size]})[0])
        return np.concatenate(batches)[:count]


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
    CREATE TABLE IF NOT EXISTS map_layout (
        path_key TEXT NOT NULL,
        model    TEXT NOT NULL,
        x        REAL NOT NULL,
        y        REAL NOT NULL,
        PRIMARY KEY (path_key, model)
    );
    CREATE TABLE IF NOT EXISTS map_layout_3d (
        path_key TEXT NOT NULL,
        model    TEXT NOT NULL,
        x        REAL NOT NULL,
        y        REAL NOT NULL,
        z        REAL NOT NULL,
        PRIMARY KEY (path_key, model)
    );
    """

    def __init__(self, path, keep_open=False):
        """keep_open: hold one connection for the store's lifetime (the analysis process).
        Otherwise every call opens and closes its own, so no file stays locked."""
        self.path = Path(path)
        self._keep_open = keep_open
        self._connection = None

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        # WAL: the UI reads while the analysis process writes. synchronous=NORMAL: with WAL
        # this is still crash-safe, but syncs to disk only at checkpoints (every ~1000 pages)
        # instead of on every commit, which matters on slow SSDs.
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA synchronous=NORMAL')
        connection.executescript(self._SCHEMA)
        if connection.execute('PRAGMA user_version').fetchone()[0] < _FAILURES_VERSION:
            with connection:  # a failure is remembered only until the decoder improves: retry them once
                connection.execute('DELETE FROM embeddings WHERE error IS NOT NULL')
                connection.execute(f'PRAGMA user_version = {_FAILURES_VERSION}')
        return connection

    @contextmanager
    def _open(self):
        if not self._keep_open:
            with closing(self._connect()) as connection:
                yield connection
            return
        if self._connection is None:
            self._connection = self._connect()
        yield self._connection

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def fingerprints(self, model=MODEL_ID):
        """{path_key: (size, mtime_ns)} of stored results (embeddings and errors) for a model."""
        with self._open() as connection:
            rows = connection.execute('SELECT path_key, file_size, file_mtime_ns FROM embeddings WHERE model = ?',
                                      (model,)).fetchall()
        return {key: (size, mtime) for key, size, mtime in rows}

    def save(self, path_key, fingerprint, matrix, model=MODEL_ID):
        self._write(path_key, fingerprint, model, len(matrix), encode(matrix), None)

    def save_error(self, path_key, fingerprint, error, model=MODEL_ID):
        self._write(path_key, fingerprint, model, 0, None, str(error)[:500])

    def _write(self, path_key, fingerprint, model, frames, data, error):
        with self._open() as connection, connection:
            connection.execute('INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                               (path_key, model, fingerprint[0], fingerprint[1], SAMPLE_RATE, CHUNK_SECONDS,
                                frames, EMBEDDING_DIM, ENCODING, data, error,
                                datetime.now(UTC).isoformat(timespec='seconds')))

    def load(self, path_key, model=MODEL_ID):
        """(frames, 2048) float16 array, or None if missing or failed."""
        with self._open() as connection:
            row = connection.execute('SELECT frames, dim, data FROM embeddings WHERE path_key = ? AND model = ? '
                                     'AND data IS NOT NULL', (path_key, model)).fetchone()
        return decode(row[2], row[0], row[1]) if row else None

    def failure(self, path_key, model=MODEL_ID):
        """Why a track could not be analysed (text), or None if it was analysed or not tried."""
        with self._open() as connection:
            row = connection.execute('SELECT error FROM embeddings WHERE path_key = ? AND model = ? '
                                     'AND error IS NOT NULL', (path_key, model)).fetchone()
        return row[0] if row else None

    def update_fingerprint(self, path_key, fingerprint):
        """After a tag-only edit the audio is unchanged: keep the embedding current."""
        with self._open() as connection, connection:
            connection.execute('UPDATE embeddings SET file_size = ?, file_mtime_ns = ? WHERE path_key = ?',
                               (fingerprint[0], fingerprint[1], path_key))

    def load_many(self, path_keys=None, model=MODEL_ID):
        """{path_key: (frames, 2048) float16 array} of analysed tracks (all, or these keys)."""
        with self._open() as connection:
            rows = connection.execute('SELECT path_key, frames, dim, data FROM embeddings WHERE model = ? '
                                      'AND data IS NOT NULL', (model,)).fetchall()
        wanted = None if path_keys is None else set(path_keys)
        return {key: decode(data, frames, dim) for key, frames, dim, data in rows
                if wanted is None or key in wanted}

    # -- map layout: 2D positions of the similarity map (a cache, like the embeddings) --

    def save_layout(self, positions, model=MODEL_ID):
        """Replace the stored map with {path_key: (x, y)}."""
        with self._open() as connection, connection:
            connection.execute('DELETE FROM map_layout WHERE model = ?', (model,))
            connection.executemany('INSERT INTO map_layout VALUES (?, ?, ?, ?)',
                                   [(key, model, float(x), float(y)) for key, (x, y) in positions.items()])

    def load_layout(self, model=MODEL_ID):
        with self._open() as connection:
            rows = connection.execute('SELECT path_key, x, y FROM map_layout WHERE model = ?', (model,)).fetchall()
        return {key: (x, y) for key, x, y in rows}

    def save_layout_3d(self, positions, model=MODEL_ID):
        """Replace the stored 3D view with {path_key: (x, y, z)}."""
        with self._open() as connection, connection:
            connection.execute('DELETE FROM map_layout_3d WHERE model = ?', (model,))
            connection.executemany('INSERT INTO map_layout_3d VALUES (?, ?, ?, ?, ?)',
                                   [(key, model, float(x), float(y), float(z)) for key, (x, y, z) in positions.items()])

    def load_layout_3d(self, model=MODEL_ID):
        with self._open() as connection:
            rows = connection.execute('SELECT path_key, x, y, z FROM map_layout_3d WHERE model = ?', (model,)).fetchall()
        return {key: (x, y, z) for key, x, y, z in rows}

    def counts(self, model=MODEL_ID):
        """(analysed, failed) number of tracks."""
        with self._open() as connection:
            return connection.execute('SELECT COUNT(data), COUNT(error) FROM embeddings WHERE model = ?',
                                      (model,)).fetchone()


BELOW_NORMAL_PRIORITY_CLASS = 0x4000
PROCESS_MODE_BACKGROUND_BEGIN = 0x00100000


def _lower_process_priority():
    """Run as a Windows background process: low CPU, disk and memory priority, so
    the UI, Traktor or a media player reading from the same disk always go first."""
    if os.name != 'nt':
        return
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    # Declare the types: without them ctypes passes the 64-bit process handle as a
    # 32-bit int, and Windows silently ignores the call.
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.SetPriorityClass.restype = wintypes.BOOL
    process = kernel32.GetCurrentProcess()
    # Background mode lowers the I/O priority, which a priority class alone does not.
    # It resets the class to normal, so set below-normal afterwards.
    kernel32.SetPriorityClass(process, PROCESS_MODE_BACKGROUND_BEGIN)
    kernel32.SetPriorityClass(process, BELOW_NORMAL_PRIORITY_CLASS)


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
        store = EmbeddingStore(store_path, keep_open=True)
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
    store.close()  # checkpoints the WAL file back into embeddings.sqlite

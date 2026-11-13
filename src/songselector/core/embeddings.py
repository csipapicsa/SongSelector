"""Audio embeddings: one vector per window of audio, for every model in core/embedding_models.py.

CNN14 (PANNs) gives one 2048-value vector per 5 seconds; the CLAP models one per 10 s (LAION) or 7 s (Microsoft).
Every model is an ONNX file taking raw mono audio at its own sample rate. The analysis process decodes each file
once and resamples it for every model that still needs the track; each model has its own cache file.

CNN14 uses the same model and preprocessing as the DJ mix segmentation project
(see docs/research/audio_embeddings.md): mono, 32 kHz, 5 s chunks, the last
chunk zero-padded. Decoding uses soundfile + soxr instead of librosa, and the
model runs through onnxruntime instead of PyTorch; both give identical
embeddings to the original pipeline (verified on a real track).

Embeddings are a cache that can be recomputed, so they live in their own SQLite
file (embeddings.sqlite) instead of library.sqlite, which holds user data.

Analysis runs in a separate process (run_analysis) that never loads Qt:
PyQt5 ships an older MSVC runtime that makes onnxruntime crash when it loads
after Qt, and a crashing decoder on a broken file must not take the app down.
This module must therefore not import PyQt5 or songselector.config.
"""
import os
import queue
import sqlite3
import zlib
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from songselector.core.embedding_models import CNN14
from songselector.core.embedding_models import model as model_spec
from songselector.env import getenv

# CNN14, the default model (names kept from before there were several models).
MODEL_ID = CNN14.id
MODEL_FILE_NAME = CNN14.audio_file
SAMPLE_RATE = CNN14.sample_rate
CHUNK_SECONDS = CNN14.chunk_seconds
CHUNK_SAMPLES = CNN14.chunk_samples
EMBEDDING_DIM = CNN14.dim
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
    """(mono float32 at the file's own rate, that rate, problem): problem is None, or the error that stopped
    libsndfile after enough was decoded. Raises if the file cannot be opened or too little was decoded."""
    import soundfile
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
    return mono.astype(np.float32, copy=False), sample_rate, problem


def _resample(audio, source_rate, rate):
    """soxr, high quality: at 32 kHz identical to librosa.load(sr=32000) (docs/research/audio_embeddings.md)."""
    import soxr
    if source_rate != rate and len(audio):
        audio = soxr.resample(audio, source_rate, rate, quality='HQ')
    return audio.astype(np.float32, copy=False)


def _read_av(path, should_stop, rate=SAMPLE_RATE):
    """Mono float32 at `rate` decoded with FFmpeg (PyAV). It reads what libsndfile cannot: AAC
    (.m4a, .mp4) and MP3s with damaged frames, which FFmpeg skips and reads on past, as its own
    command line does. A file read without any damage is returned whatever its length; after damage
    it must pass _enough. Raises (ImportError if PyAV is missing) when too little could be decoded."""
    import av
    resampler = av.AudioResampler(format='fltp', rate=rate)  # keeps the channels; averaged below
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
    if not len(audio) or (damaged and not _enough(len(audio) / rate, expected)):
        raise ValueError(f'FFmpeg decoded only {len(audio) / rate:.0f} s of {expected:.0f} s')
    return audio


def load_audio_rates(path, rates, should_stop=lambda: False):
    """{rate: mono float32 audio} for each sample rate; at 32 kHz it matches librosa.load(path, sr=32000, mono=True).

    libsndfile decodes the file once (MP3, FLAC, WAV) and that is resampled to every rate. If it cannot open the
    file (AAC) or stops at a damaged frame, FFmpeg is tried as well and the longer result is used; see _enough for
    how little may be missing. If neither decodes enough, libsndfile's error is raised.
    """
    native, problem = None, None
    try:
        mono, native_rate, problem = _read_soundfile(path, should_stop)
        native = (mono, native_rate)
    except Cancelled:
        raise
    except Exception as error:
        problem = error
    result = {}
    for rate in sorted(set(rates)):
        candidates = [] if native is None else [_resample(native[0], native[1], rate)]
        if problem is not None:
            try:
                candidates.append(_read_av(path, should_stop, rate))
            except Cancelled:
                raise
            except Exception:  # PyAV not installed, or FFmpeg cannot read the file either
                pass
        if not candidates:
            raise problem
        result[rate] = max(candidates, key=len)
    return result


def load_audio(path, should_stop=lambda: False):
    """Mono float32 at 32 kHz (CNN14's rate); see load_audio_rates."""
    return load_audio_rates(path, [SAMPLE_RATE], should_stop)[SAMPLE_RATE]


def split_chunks(audio, size=CHUNK_SAMPLES):
    """(n_windows, size) array; the last window is zero-padded."""
    count = max(1, -(-len(audio) // size))
    padded = np.zeros(count * size, dtype=np.float32)
    padded[:len(audio)] = audio
    return padded.reshape(count, size)


def encode(matrix):
    return zlib.compress(np.ascontiguousarray(matrix, dtype=np.float16).tobytes(), 6)


def decode(blob, frames, dim=EMBEDDING_DIM):
    return np.frombuffer(zlib.decompress(blob), dtype=np.float16).reshape(frames, dim)


# Fastest first. Which ones exist depends on the installed package: onnxruntime-directml
# (default; any DirectX 12 GPU, plus CPU), onnxruntime-gpu (CUDA, needs CUDA 12 + cuDNN 9 DLLs)
# or onnxruntime (CPU only).
PREFERRED_PROVIDERS = ('CUDAExecutionProvider', 'DmlExecutionProvider', 'CPUExecutionProvider')
BATCH_SIZES = CNN14.batch_sizes  # windows per model call; each model has its own (core/embedding_models.py)
# Folder with CUDA 12 / cuDNN 9 DLLs to use, e.g. ...\site-packages\torch\lib of a CUDA PyTorch.
CUDA_DLL_DIR_VARIABLE = 'CUDA_DLL_DIR'  # read as SONGSELECTOR_CUDA_DLL_DIR (see env.py)


class OnnxEmbedder:
    """An embedding model through onnxruntime, on the GPU when available. Loading takes a few seconds."""

    spec = CNN14

    def __init__(self, model_path, threads=None, model_id=MODEL_ID):
        import onnxruntime
        self.spec = model_spec(model_id)
        if 'CUDAExecutionProvider' in onnxruntime.get_available_providers() and hasattr(onnxruntime, 'preload_dlls'):
            try:  # CUDA 12 / cuDNN 9 DLLs: from SONGSELECTOR_CUDA_DLL_DIR, else the nvidia-* pip packages
                onnxruntime.preload_dlls(directory=getenv(CUDA_DLL_DIR_VARIABLE) or None)
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
        self.batch_size = self.spec.batch_sizes.get(self.provider, 1)

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
        """(n_windows, dim) float32 embeddings of mono audio at the model's sample rate."""
        chunks = split_chunks(audio, self.spec.chunk_samples)
        count, size = len(chunks), self.batch_size
        if size > 1 and count % size:
            # Every call gets the same shape: GPU providers re-plan the model for each new
            # input shape. The zero padding is cut off again below.
            chunks = np.concatenate([chunks, np.zeros((size - count % size, chunks.shape[1]), dtype=np.float32)])
        batches = []
        for start in range(0, len(chunks), size):
            if should_stop():
                raise Cancelled()
            batches.append(self.session.run(['embedding'], {self.input_name: chunks[start:start + size]})[0])
        return np.concatenate(batches)[:count]


Cnn14Embedder = OnnxEmbedder  # the name from before there were several models


class EmbeddingStore:
    """One model's cache (embeddings.sqlite for CNN14): one row per track, path_key as in library.sqlite."""

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

    def __init__(self, path, keep_open=False, spec=CNN14):
        """keep_open: hold one connection for the store's lifetime (the analysis process).
        Otherwise every call opens and closes its own, so no file stays locked.
        spec: the model whose embeddings this file holds (core/embedding_models.py)."""
        self.path = Path(path)
        self.spec = spec
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

    def fingerprints(self, model=None):
        """{path_key: (size, mtime_ns)} of stored results (embeddings and errors) for a model."""
        model = model or self.spec.id
        with self._open() as connection:
            rows = connection.execute('SELECT path_key, file_size, file_mtime_ns FROM embeddings WHERE model = ?',
                                      (model,)).fetchall()
        return {key: (size, mtime) for key, size, mtime in rows}

    def save(self, path_key, fingerprint, matrix, model=None):
        model = model or self.spec.id
        self._write(path_key, fingerprint, model, len(matrix), encode(matrix), None)

    def save_error(self, path_key, fingerprint, error, model=None):
        model = model or self.spec.id
        self._write(path_key, fingerprint, model, 0, None, str(error)[:500])

    def _write(self, path_key, fingerprint, model, frames, data, error):
        with self._open() as connection, connection:
            connection.execute('INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                               (path_key, model, fingerprint[0], fingerprint[1], self.spec.sample_rate,
                                self.spec.chunk_seconds, frames, self.spec.dim, ENCODING, data, error,
                                datetime.now(UTC).isoformat(timespec='seconds')))

    def load(self, path_key, model=None):
        """(frames, 2048) float16 array, or None if missing or failed."""
        model = model or self.spec.id
        with self._open() as connection:
            row = connection.execute('SELECT frames, dim, data FROM embeddings WHERE path_key = ? AND model = ? '
                                     'AND data IS NOT NULL', (path_key, model)).fetchone()
        return decode(row[2], row[0], row[1]) if row else None

    def failure(self, path_key, model=None):
        """Why a track could not be analysed (text), or None if it was analysed or not tried."""
        model = model or self.spec.id
        with self._open() as connection:
            row = connection.execute('SELECT error FROM embeddings WHERE path_key = ? AND model = ? '
                                     'AND error IS NOT NULL', (path_key, model)).fetchone()
        return row[0] if row else None

    def update_fingerprint(self, path_key, fingerprint):
        """After a tag-only edit the audio is unchanged: keep the embedding current."""
        with self._open() as connection, connection:
            connection.execute('UPDATE embeddings SET file_size = ?, file_mtime_ns = ? WHERE path_key = ?',
                               (fingerprint[0], fingerprint[1], path_key))

    def load_many(self, path_keys=None, model=None):
        """{path_key: (frames, 2048) float16 array} of analysed tracks (all, or these keys)."""
        model = model or self.spec.id
        with self._open() as connection:
            rows = connection.execute('SELECT path_key, frames, dim, data FROM embeddings WHERE model = ? '
                                      'AND data IS NOT NULL', (model,)).fetchall()
        wanted = None if path_keys is None else set(path_keys)
        return {key: decode(data, frames, dim) for key, frames, dim, data in rows
                if wanted is None or key in wanted}

    # -- map layout: 2D positions of the similarity map (a cache, like the embeddings) --

    def save_layout(self, positions, model=None):
        """Replace the stored map with {path_key: (x, y)}."""
        model = model or self.spec.id
        with self._open() as connection, connection:
            connection.execute('DELETE FROM map_layout WHERE model = ?', (model,))
            connection.executemany('INSERT INTO map_layout VALUES (?, ?, ?, ?)',
                                   [(key, model, float(x), float(y)) for key, (x, y) in positions.items()])

    def load_layout(self, model=None):
        model = model or self.spec.id
        with self._open() as connection:
            rows = connection.execute('SELECT path_key, x, y FROM map_layout WHERE model = ?', (model,)).fetchall()
        return {key: (x, y) for key, x, y in rows}

    def save_layout_3d(self, positions, model=None):
        """Replace the stored 3D view with {path_key: (x, y, z)}."""
        model = model or self.spec.id
        with self._open() as connection, connection:
            connection.execute('DELETE FROM map_layout_3d WHERE model = ?', (model,))
            connection.executemany('INSERT INTO map_layout_3d VALUES (?, ?, ?, ?, ?)',
                                   [(key, model, float(x), float(y), float(z)) for key, (x, y, z) in positions.items()])

    def load_layout_3d(self, model=None):
        model = model or self.spec.id
        with self._open() as connection:
            rows = connection.execute('SELECT path_key, x, y, z FROM map_layout_3d WHERE model = ?', (model,)).fetchall()
        return {key: (x, y, z) for key, x, y, z in rows}

    def counts(self, model=None):
        """(analysed, failed) number of tracks."""
        model = model or self.spec.id
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


def run_analysis(models, jobs, events, stop):
    """Entry point of the analysis process.

    models: [(model_id, model_path, store_path, factory)], one per enabled model; factory(model_path) builds the
    embedder (picklable: a module-level class, or functools.partial of one). Each track is decoded once and
    resampled for every model whose cache does not have it yet.

    Reads (path_key, file_path) jobs from the `jobs` queue until `stop` is set and reports on `events`:
      ('ready', provider)        models loaded; provider of the first, e.g. CUDAExecutionProvider
      ('warning', message)       a model could not be loaded; the others go on
      ('start', key, file name)  analysing a file (if the process dies now, this file caused it)
      ('done', key, status)      status: analysed | current | missing | failed | cancelled
      ('fatal', message)         cannot continue (e.g. no model file could be loaded)
    """
    _lower_process_priority()
    workers, problem = [], 'no embedding model'
    for model_id, model_path, store_path, factory in models:
        spec = model_spec(model_id)
        try:
            embedder = factory(model_path)
            store = EmbeddingStore(store_path, keep_open=True, spec=spec)
            workers.append((spec, embedder, store, store.fingerprints()))
        except Exception as error:
            problem = f'{type(error).__name__}: {error}'
            if len(models) > 1:
                events.put(('warning', f'{spec.name} could not be loaded ({problem})'))
    if not workers:
        events.put(('fatal', problem))
        return
    events.put(('ready', getattr(workers[0][1], 'provider', 'CPUExecutionProvider')))
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
        todo = [worker for worker in workers if worker[3].get(key) != fingerprint]
        if not todo:
            events.put(('done', key, 'current'))
            continue
        events.put(('start', key, Path(path).name))
        try:
            audio = load_audio_rates(path, [spec.sample_rate for spec, *_ in todo], stop.is_set)
        except Cancelled:
            events.put(('done', key, 'cancelled'))
            break
        except Exception as error:  # undecodable file: remember it, retry only if the file changes
            for _spec, _embedder, store, known in todo:
                store.save_error(key, fingerprint, f'{type(error).__name__}: {error}')
                known[key] = fingerprint
            events.put(('done', key, 'failed'))
            continue
        status, cancelled = 'failed', False
        for spec, embedder, store, known in todo:
            try:
                store.save(key, fingerprint, embedder.embed(audio[spec.sample_rate], stop.is_set))
                status = 'analysed'
            except Cancelled:
                cancelled = True
                break
            except Exception as error:
                store.save_error(key, fingerprint, f'{type(error).__name__}: {error}')
            known[key] = fingerprint
        if cancelled:
            events.put(('done', key, 'cancelled'))
            break
        events.put(('done', key, status))
    for _spec, _embedder, store, _known in workers:
        store.close()  # checkpoints the WAL file back into the cache file

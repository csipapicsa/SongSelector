"""Audio -> embedding windows for the models compared with CNN14 (docs/research/model_candidates.md).

All three are Essentia's ONNX files (downloaded by `python fetch_models.py`). Essentia itself has no
Windows build here, so the audio front ends (mel spectrograms) are written in numpy and checked in
`selfcheck.py`: against librosa, and by the models' own outputs on real tracks.

Needs only numpy, soundfile, soxr, onnxruntime: run with the app's `.venv` to use the GPU (DirectML).
The mel filter matrices are made once with librosa (`selfcheck.py --prepare`, system Python).
"""
import time
from pathlib import Path

import numpy as np

CACHE = Path(__file__).resolve().parents[4] / '.research_cache'
MODELS = CACHE / 'models'


# -- audio ----------------------------------------------------------------------------------------

def decode(path, rates):
    """Mono float32 of the file at each sample rate in `rates`: {rate: samples}. Resampled from the
    file's own rate (soxr, high quality), so a 48 kHz model does not get an upsampled 32 kHz signal."""
    import soundfile
    import soxr
    blocks = []
    with soundfile.SoundFile(str(path)) as audio_file:
        native = audio_file.samplerate
        while True:
            block = audio_file.read(1 << 20, dtype='float32', always_2d=True)
            if not len(block):
                break
            blocks.append(block.mean(axis=1))
    mono = np.concatenate(blocks) if blocks else np.zeros(0, np.float32)
    return {rate: (mono if rate == native else soxr.resample(mono, native, rate, quality='HQ')).astype(np.float32)
            for rate in rates}


def mel_filters(name):
    """(n_mels, n_fft // 2 + 1) filter matrix saved by `selfcheck.py --prepare`."""
    return np.load(MODELS / f'mel_{name}.npy')


def power_spectrogram(signal, n_fft, hop, power):
    """|STFT|**power, shape (frames, n_fft // 2 + 1): Hann window, zero padding of n_fft // 2 at both
    ends (librosa's default centring)."""
    padded = np.pad(signal, n_fft // 2)
    frames = 1 + (len(padded) - n_fft) // hop
    if frames <= 0:
        return np.zeros((0, n_fft // 2 + 1), np.float32)
    window = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n_fft) / n_fft)).astype(np.float32)
    out = np.empty((frames, n_fft // 2 + 1), np.float32)
    step = 4096
    for start in range(0, frames, step):  # in blocks: a 6-minute track at 48 kHz is large
        index = np.arange(n_fft)[None, :] + hop * np.arange(start, min(frames, start + step))[:, None]
        spectrum = np.abs(np.fft.rfft(padded[index] * window, axis=1))
        out[start:start + step] = spectrum ** power
    return out


def musicnn_mel(signal16k):
    """Essentia/musicnn input: 96 mel bands (Slaney scale and area normalisation, 0-8 kHz) of a
    512-sample, hop 256 power spectrogram, compressed as log10(10000 x + 1). Shape (frames, 96)."""
    mel = power_spectrogram(signal16k, 512, 256, 2.0) @ mel_filters('musicnn').T
    return np.log10(10000.0 * mel + 1.0).astype(np.float32)


def openl3_mel(signal48k):
    """OpenL3 input for ONE 1 s window (48000 samples): (128, 199, 1). Magnitude spectrogram, n_fft
    2048, hop 242, 128 HTK mel bands; decibels relative to the window's loudest value, floor -80 dB
    (kapre's decibel scaling, as in the openl3 package)."""
    mel = power_spectrogram(signal48k, 2048, 242, 1.0) @ mel_filters('openl3').T
    decibel = 10.0 * np.log10(np.maximum(mel, 1e-10))
    decibel = np.maximum(decibel - decibel.max(), -80.0)
    return decibel.T[:, :, None].astype(np.float32)


# -- models ---------------------------------------------------------------------------------------

def _session(file, optimise=True):
    """GPU (CUDA or DirectML) if there is one, else CPU. MusiCNN's graph fails to compile on DirectML
    with graph optimisation on (onnxruntime then silently falls back to the CPU): `optimise=False`."""
    import onnxruntime
    names = onnxruntime.get_available_providers()
    providers = [p for p in ('CUDAExecutionProvider', 'DmlExecutionProvider') if p in names] + ['CPUExecutionProvider']
    options = onnxruntime.SessionOptions()
    options.enable_mem_pattern = False  # DirectML requirement
    options.intra_op_num_threads = options.inter_op_num_threads = 1  # the GPU does the work; more threads only compete
    if not optimise:
        options.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_DISABLE_ALL
    return onnxruntime.InferenceSession(str(MODELS / file), options, providers=providers)


def _run_batches(session, output, array, batch):
    """Run in batches of a fixed size (the last one padded): GPU providers re-plan for every new shape."""
    outputs = []
    for start in range(0, len(array), batch):
        part = array[start:start + batch]
        if len(part) < batch:
            part = np.concatenate([part, np.zeros((batch - len(part),) + part.shape[1:], np.float32)])
        outputs.append(session.run([output], {session.get_inputs()[0].name: part})[0][:min(batch, len(array) - start)])
    return np.concatenate(outputs) if outputs else np.zeros((0, 1), np.float32)


def _patches(mel, size, hop):
    """Consecutive (size, bands) pieces of a (frames, bands) spectrogram; a short one is zero-padded."""
    if len(mel) < size:
        mel = np.concatenate([mel, np.zeros((size - len(mel), mel.shape[1]), np.float32)])
    starts = range(0, len(mel) - size + 1, hop)
    return np.stack([mel[s:s + size] for s in starts])


class Model:
    rate = 16000
    name = ''
    dim = 0

    def windows(self, audio):  # audio: {rate: samples} -> (n, dim) embeddings, one row per window
        raise NotImplementedError


class MusiCNN(Model):
    """MSD-MusiCNN: 3 s patches (187 frames), 200-value embedding."""
    name, dim = 'musicnn', 200

    def __init__(self):
        self.session = _session('msd-musicnn-1.onnx', optimise=False)

    def windows(self, audio, with_tags=False):
        patches = _patches(musicnn_mel(audio[16000]), 187, 187)
        embeddings = _run_batches(self.session, 'embeddings', patches, 32)
        return (embeddings, _run_batches(self.session, 'activations', patches, 32)) if with_tags else embeddings


class DiscogsEffNet(Model):
    """Discogs-EffNet: 128-frame patches (about 2 s) of the same mel features, 1280-value embedding."""
    name, dim = 'discogs_effnet', 1280

    def __init__(self):
        self.session = _session('discogs-effnet-bsdynamic-1.onnx')

    def windows(self, audio, with_tags=False):
        patches = _patches(musicnn_mel(audio[16000]), 128, 128)
        embeddings = _run_batches(self.session, 'embeddings', patches, 32)
        return (embeddings, _run_batches(self.session, 'activations', patches, 32)) if with_tags else embeddings


class OpenL3(Model):
    """OpenL3 (music, 128 mel, 512 values): a 1 s window every STEP seconds (every 3rd second: the
    spectrogram on the CPU is the cost, and neighbouring seconds are alike)."""
    name, dim, rate = 'openl3', 512, 48000
    STEP = 3

    def __init__(self):
        self.session = _session('openl3-music-mel128-emb512-3.onnx')

    def windows(self, audio):
        signal = audio[48000]
        count = max(1, len(signal) // 48000)
        pieces = [signal[i * 48000:(i + 1) * 48000] for i in range(0, count, self.STEP)]
        pieces[-1] = np.pad(pieces[-1], (0, 48000 - len(pieces[-1])))
        mel = np.stack([openl3_mel(piece) for piece in pieces])
        return _run_batches(self.session, 'embeddings', mel, 32)


ALL = {'musicnn': MusiCNN, 'discogs_effnet': DiscogsEffNet, 'openl3': OpenL3}


def pool(windows):
    """One vector per track: mean and standard deviation over its windows."""
    return np.concatenate([windows.mean(0), windows.std(0)]).astype(np.float32)


def timed(function, *args):
    start = time.perf_counter()
    result = function(*args)
    return result, time.perf_counter() - start

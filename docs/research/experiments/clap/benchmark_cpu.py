"""CPU cost of CLAP models for free-text track search (see docs/research/text_search_clap.md).

Question: can a text-to-audio model (CLAP) embed a DJ library on the CPU alone, in acceptable time,
and answer a typed query fast enough to feel interactive?

Each (model, thread count) runs in its own process (`--worker`), so thread settings and memory
figures do not leak between runs. A worker measures:
  load      model load time from the local cache, memory after loading, peak memory
  window    one audio window through the audio encoder (batch 1 and batch 8), median of repeats
  text      the first query (cold) and the median of 10 single queries
  tracks    real tracks: decode (soundfile + soxr, as the app does) and embed every window

Runs in an isolated environment, because msclap pins transformers < 5 and numpy < 2:

    python -m venv --system-site-packages .research_cache\\venv-clap
    .research_cache\\venv-clap\\Scripts\\python -m pip install msclap==1.3.4 psutil soxr soundfile
    set HF_HOME=.research_cache\\hf
    .research_cache\\venv-clap\\Scripts\\python docs\\research\\experiments\\clap\\benchmark_cpu.py --tracks E:\\DJ

PyTorch on the CPU only (CUDA hidden). The app would run an ONNX export through onnxruntime; that
is measured separately once a model is chosen.
"""
import argparse
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[4]
RESULTS = REPO / 'docs' / 'research' / 'experiments' / 'results'
AUDIO_SUFFIXES = {'.mp3', '.flac', '.wav'}
BATCH = 8

# The light version of each family, plus LAION's music-trained model for reference.
MODELS = {
    'laion-unfused': 'laion/clap-htsat-unfused',   # HTSAT-tiny + RoBERTa, general audio, 615 MB
    'laion-music': 'laion/larger_clap_music',      # HTSAT-base + RoBERTa, music, 776 MB
    'ms-2023': 'microsoft/msclap 2023',            # HTSAT + GPT-2, general audio, 690 MB
}

PROMPTS = [
    'dark rolling drum and bass with a heavy reese bassline',
    'uplifting breakbeat with piano chords',
    'minimal techno, hypnotic and repetitive',
    'female vocal house track',
    'tribal percussion and deep sub bass',
    'acid squelchy 303 line',
    'jungle with chopped amen breaks',
    'chilled downtempo with warm pads',
    'aggressive distorted electro',
    'soulful disco with strings',
]


# ---- Models: the same small interface for both families ------------------------------------

class LaionClap:
    def __init__(self, repo):
        from transformers import ClapModel, ClapProcessor
        self.model = ClapModel.from_pretrained(repo).eval()
        self.processor = ClapProcessor.from_pretrained(repo)
        self.rate = self.processor.feature_extractor.sampling_rate        # 48 kHz
        self.window = self.processor.feature_extractor.nb_max_samples      # 10 s
        self.audio_parts = (self.model.audio_model, self.model.audio_projection)
        self.text_parts = (self.model.text_model, self.model.text_projection)

    def prepare(self, windows):
        """Mel features (numpy, outside the network). Timed separately: it is part of the cost."""
        return self.processor.feature_extractor(list(windows), sampling_rate=self.rate, return_tensors='pt')

    device = 'cpu'

    def audio_to(self, device):
        """Only the audio half on `device` (the text half is not needed for analysis)."""
        for part in self.audio_parts:
            part.to(device)
        self.device = device

    def embed_prepared(self, features):
        import torch
        with torch.inference_mode():
            features = {name: value.to(self.device) for name, value in features.items()}
            return self.model.get_audio_features(**features).cpu().numpy()

    def embed_text(self, texts):
        import torch
        inputs = self.processor.tokenizer(texts, padding=True, return_tensors='pt')
        with torch.inference_mode():
            return self.model.get_text_features(**inputs).numpy()


class MsClap:
    def __init__(self, version='2023'):
        from msclap import CLAP
        self.clap = CLAP(version=version, use_cuda=False)
        self.rate = self.clap.args.sampling_rate                  # 44.1 kHz
        self.window = self.clap.args.sampling_rate * self.clap.args.duration   # 7 s
        self.audio_parts = (self.clap.clap.audio_encoder,)
        self.text_parts = (self.clap.clap.caption_encoder,)

    def prepare(self, windows):
        import torch
        return torch.from_numpy(np.ascontiguousarray(windows, dtype=np.float32))  # the mel is inside the network

    device = 'cpu'

    def audio_to(self, device):
        self.clap.clap.audio_encoder.to(device)
        self.device = device

    def embed_prepared(self, audio):
        import torch
        with torch.inference_mode():
            return self.clap.clap.audio_encoder(audio.to(self.device))[0].cpu().numpy()

    def embed_text(self, texts):
        return self.clap.get_text_embeddings(texts).numpy()


def load_model(key):
    return MsClap('2023') if key == 'ms-2023' else LaionClap(MODELS[key])


# ---- Helpers ------------------------------------------------------------------------------

def decode(path, rate):
    """Mono float32 at `rate`: libsndfile decode + soxr resampling, the app's decoding stack."""
    import soundfile
    import soxr
    audio, native = soundfile.read(str(path), dtype='float32', always_2d=True)
    audio = audio.mean(axis=1)
    return soxr.resample(audio, native, rate, quality='HQ').astype(np.float32) if native != rate else audio


def windows_of(audio, size):
    """Non-overlapping windows covering the whole track; the last is zero-padded."""
    count = max(1, -(-len(audio) // size))
    padded = np.zeros(count * size, dtype=np.float32)
    padded[:len(audio)] = audio
    return padded.reshape(count, size)


def median_ms(function, repeats, warmup=2):
    for _ in range(warmup):
        function()
    times = []
    for _ in range(repeats):
        started = time.perf_counter()
        function()
        times.append((time.perf_counter() - started) * 1000)
    return statistics.median(times)


def parameters(parts):
    return sum(p.numel() for part in parts for p in part.parameters())


def memory_mb():
    import psutil
    info = psutil.Process().memory_info()
    return info.rss / 1e6, getattr(info, 'peak_wset', info.rss) / 1e6


# ---- Worker: one model, one thread count ---------------------------------------------------

def worker(key, threads, tracks):
    import torch
    torch.set_num_threads(threads)
    torch.set_num_interop_threads(1)

    started = time.perf_counter()
    model = load_model(key)
    load_s = time.perf_counter() - started
    rss_loaded, _ = memory_mb()

    rng = np.random.default_rng(0)
    one = rng.uniform(-0.3, 0.3, (1, model.window)).astype(np.float32)
    batch = rng.uniform(-0.3, 0.3, (BATCH, model.window)).astype(np.float32)
    prepared_one, prepared_batch = model.prepare(one), model.prepare(batch)

    result = {
        'model': key, 'threads': threads, 'rate': model.rate, 'window_s': model.window / model.rate,
        'embedding_dim': int(model.embed_text(['x']).shape[1]),
        'audio_params_m': parameters(model.audio_parts) / 1e6, 'text_params_m': parameters(model.text_parts) / 1e6,
        'load_s': load_s, 'rss_after_load_mb': rss_loaded,
        'prepare_ms_per_window': median_ms(lambda: model.prepare(batch), 5) / BATCH,
        'window_ms_batch1': median_ms(lambda: model.embed_prepared(prepared_one), 10),
        'window_ms_batch8': median_ms(lambda: model.embed_prepared(prepared_batch), 5) / BATCH,
    }

    # Text: a fresh query string each time, as a user would type.
    started = time.perf_counter()
    model.embed_text(['warm-up query, never timed before'])
    result['text_ms_cold'] = (time.perf_counter() - started) * 1000
    times = []
    for prompt in PROMPTS:
        started = time.perf_counter()
        model.embed_text([prompt])
        times.append((time.perf_counter() - started) * 1000)
    result['text_ms_median'] = statistics.median(times)

    # Ranking a library: cosine similarity of one query against 3,000 track vectors.
    library = rng.standard_normal((3000, result['embedding_dim'])).astype(np.float32)
    library /= np.linalg.norm(library, axis=1, keepdims=True)
    query = library[0]
    result['rank_3000_ms'] = median_ms(lambda: np.argpartition(-(library @ query), 10)[:10], 20)

    per_track = []
    for path in tracks:
        started = time.perf_counter()
        audio = decode(path, model.rate)
        decode_s = time.perf_counter() - started
        windows = windows_of(audio, model.window)
        started = time.perf_counter()
        for start in range(0, len(windows), BATCH):
            model.embed_prepared(model.prepare(windows[start:start + BATCH]))
        embed_s = time.perf_counter() - started
        per_track.append({'minutes': len(audio) / model.rate / 60, 'windows': len(windows),
                          'decode_s': decode_s, 'embed_s': embed_s})
    result['tracks'] = per_track
    result['rss_peak_mb'] = memory_mb()[1]
    print(json.dumps(result))


# ---- Main: pick tracks, run every worker, summarise ----------------------------------------

def pick_tracks(folder, count, seed):
    candidates = sorted(p for p in Path(folder).rglob('*') if p.suffix.lower() in AUDIO_SUFFIXES and p.is_file())
    random.Random(seed).shuffle(candidates)
    picked = []
    for path in candidates:
        try:
            if 2 <= len(decode(path, 16000)) / 16000 / 60 <= 12:  # ordinary tracks, not mixes or jingles
                picked.append(path)
        except Exception:
            continue
        if len(picked) == count:
            break
    return picked


def summarise(run):
    tracks = run['tracks']
    minutes = sum(t['minutes'] for t in tracks)
    decode_per_min = sum(t['decode_s'] for t in tracks) / minutes
    embed_per_min = sum(t['embed_s'] for t in tracks) / minutes
    full_6min = 6 * (decode_per_min + embed_per_min)
    # Sampling 6 windows spread over the track instead of every window: decode stays, embedding shrinks.
    sampled_6min = 6 * decode_per_min + 6 * (run['window_ms_batch8'] + run['prepare_ms_per_window']) / 1000
    return {
        'decode_s_per_audio_min': decode_per_min, 'embed_s_per_audio_min': embed_per_min,
        'full_s_per_6min_track': full_6min, 'full_h_per_3000_tracks': full_6min * 3000 / 3600,
        'sampled6_s_per_6min_track': sampled_6min, 'sampled6_h_per_3000_tracks': sampled_6min * 3000 / 3600,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tracks', help='music folder to pick random tracks from')
    parser.add_argument('--count', type=int, default=5)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--threads', type=int, nargs='+', default=[4, 8])
    parser.add_argument('--models', nargs='+', default=list(MODELS))
    parser.add_argument('--out', type=Path, default=RESULTS / f'{date.today()}_clap_cpu.json')
    parser.add_argument('--worker', nargs=3, metavar=('MODEL', 'THREADS', 'TRACKS_JSON'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        key, threads, tracks = args.worker
        return worker(key, int(threads), json.loads(Path(tracks).read_text()))

    tracks = [str(p) for p in pick_tracks(args.tracks, args.count, args.seed)]
    track_file = REPO / '.research_cache' / 'clap_benchmark_tracks.json'
    track_file.write_text(json.dumps(tracks))
    environment = dict(os.environ, CUDA_VISIBLE_DEVICES='', HF_HUB_OFFLINE='1', TRANSFORMERS_VERBOSITY='error')
    runs = []
    for key in args.models:
        for threads in args.threads:
            print(f'{key}, {threads} threads ...', flush=True)
            output = subprocess.run([sys.executable, __file__, '--worker', key, str(threads), str(track_file)],
                                    env=environment, capture_output=True, text=True, check=True).stdout
            run = json.loads(output.strip().splitlines()[-1])
            run['summary'] = summarise(run)
            runs.append(run)
            s = run['summary']
            print(f"  window {run['window_ms_batch8']:.0f} ms (batch 8), text {run['text_ms_median']:.0f} ms, "
                  f"full 6-min track {s['full_s_per_6min_track']:.1f} s, sampled {s['sampled6_s_per_6min_track']:.1f} s")

    import torch
    report = {
        'date': str(date.today()),
        'machine': {'cpu': platform.processor(), 'logical_cpus': os.cpu_count(), 'python': platform.python_version(),
                    'torch': torch.__version__},
        'setup': {'tracks': len(tracks), 'seed': args.seed, 'batch': BATCH, 'device': 'CPU (CUDA hidden)',
                  'decode': 'soundfile + soxr HQ', 'prompts': PROMPTS},
        'runs': runs,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1))
    print(f'Wrote {args.out}')


if __name__ == '__main__':
    main()

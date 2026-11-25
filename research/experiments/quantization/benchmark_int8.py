"""Is an int8 version of the app's audio models really faster, and how much does it change the embeddings?

Question (2026-11-20): would int8 versions of CNN14 and LAION CLAP (audio) analyse a library faster, on the CPU,
on DirectML (the GPU path of the Windows app) and on CUDA? And are their embeddings close enough that the closest
tracks stay the same?

The int8 models are made from the app's own ONNX exports with onnxruntime's dynamic quantization (weights int8,
activations quantised on the fly), so they take the same raw audio as the originals. Everything else is the app's:
window length and sample rate per model, batch size per provider, half the CPU cores, the same session options.

    # 1. int8 files (needs the `onnx` package; any onnxruntime has the quantizer):
    .research_cache\\venv-ort-cuda\\Scripts\\python research\\experiments\\quantization\\benchmark_int8.py quantize
    # 2. decode 10 random tracks once, run every model x precision x provider in its own process, compare:
    .venv\\Scripts\\python research\\experiments\\quantization\\benchmark_int8.py run --tracks E:\\DJ

CPU and DirectML run in the app's environment (onnxruntime-directml); CUDA in .research_cache\\venv-ort-cuda
(onnxruntime-gpu 1.22 + NVIDIA's CUDA 12 / cuDNN 9 pip packages). Model files: dist\\models (the exports);
everything made here goes to .research_cache\\int8. The report lists no track names.
"""
import argparse
import json
import os
import platform
import random
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'src'))
from songselector.core.embedding_models import CNN14, LAION_CLAP  # noqa: E402  (pure Python, no Qt)

WORK = REPO / '.research_cache' / 'int8'
RESULTS = REPO / 'research' / 'results'
FP32_FOLDER = REPO / 'dist' / 'models'
CUDA_PYTHON = REPO / '.research_cache' / 'venv-ort-cuda' / 'Scripts' / 'python.exe'
APP_PYTHON = REPO / '.venv' / 'Scripts' / 'python.exe'
MODELS = {'cnn14': CNN14, 'laion': LAION_CLAP}
PROVIDERS = {'cpu': 'CPUExecutionProvider', 'dml': 'DmlExecutionProvider', 'cuda': 'CUDAExecutionProvider'}
DML_OPTIONS = {'performance_preference': 'high_performance', 'device_filter': 'gpu'}  # as core/embeddings.py
AUDIO_SUFFIXES = {'.mp3', '.flac', '.wav'}


def model_file(name, precision):
    spec = MODELS[name]
    return FP32_FOLDER / spec.audio_file if precision == 'fp32' else WORK / spec.audio_file.replace('.onnx', '-int8.onnx')


# ---- 1. quantize ---------------------------------------------------------------------------------------------

def quantize():
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from onnxruntime.quantization.shape_inference import quant_pre_process
    WORK.mkdir(parents=True, exist_ok=True)
    for name in MODELS:
        source, target = model_file(name, 'fp32'), model_file(name, 'int8')
        prepared = WORK / f'{name}-prepared.onnx'
        started = time.perf_counter()
        try:  # shape inference and graph clean-up first, as onnxruntime recommends
            quant_pre_process(str(source), str(prepared), skip_symbolic_shape=True)
        except Exception as error:
            print(f'{name}: pre-processing failed ({error}); quantizing the export as it is')
            prepared = source
        quantize_dynamic(str(prepared), str(target), weight_type=QuantType.QInt8)
        print(f'{name}: {source.stat().st_size / 1e6:.0f} MB -> {target.stat().st_size / 1e6:.0f} MB int8 '
              f'in {time.perf_counter() - started:.0f} s')


# ---- 2. decode the tracks once -------------------------------------------------------------------------------

def decode(folder, count, seed):
    from songselector.core.embeddings import load_audio_rates
    candidates = sorted(path for path in Path(folder).rglob('*') if path.suffix.lower() in AUDIO_SUFFIXES)
    random.Random(seed).shuffle(candidates)
    audio_dir = WORK / 'audio'
    audio_dir.mkdir(parents=True, exist_ok=True)
    tracks, decode_seconds = [], []
    for path in candidates:
        if len(tracks) == count:
            break
        started = time.perf_counter()
        try:
            rates = load_audio_rates(path, [spec.sample_rate for spec in MODELS.values()])
        except Exception:
            continue  # unreadable file: take the next one
        decode_seconds.append(time.perf_counter() - started)
        index = len(tracks)
        for rate, audio in rates.items():
            np.save(audio_dir / f'{index}-{rate}.npy', audio)
        tracks.append(len(rates[CNN14.sample_rate]) / CNN14.sample_rate)
    return tracks, decode_seconds


# ---- 3. one model x precision x provider, in its own process ---------------------------------------------------

def worker(name, precision, provider, count, threads):
    import onnxruntime
    spec = MODELS[name]
    if provider == 'cuda' and hasattr(onnxruntime, 'preload_dlls'):
        onnxruntime.preload_dlls()
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.enable_mem_pattern = False
    options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
    wanted = PROVIDERS[provider]
    providers = [(wanted, DML_OPTIONS) if provider == 'dml' else wanted, 'CPUExecutionProvider']
    started = time.perf_counter()
    session = onnxruntime.InferenceSession(str(model_file(name, precision)), options, providers=providers)
    load = time.perf_counter() - started
    used = session.get_providers()[0]
    if used != wanted:
        print(json.dumps({'error': f'{wanted} not available, got {used}'}))
        return
    input_name = session.get_inputs()[0].name
    size = spec.batch_sizes.get(wanted, 1)
    from songselector.core.embeddings import split_chunks
    warm = np.zeros((size, spec.chunk_samples), dtype=np.float32)
    for _ in range(2):  # the first calls of a shape include planning (and CUDA/DirectML set-up)
        session.run(['embedding'], {input_name: warm})
    per_track, windows = [], 0
    out = WORK / 'embeddings' / f'{name}-{precision}-{provider}'
    out.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        audio = np.load(WORK / 'audio' / f'{index}-{spec.sample_rate}.npy')
        chunks = split_chunks(audio, spec.chunk_samples)
        total = len(chunks)
        if size > 1 and total % size:  # every call the same shape, as the app does
            chunks = np.concatenate([chunks, np.zeros((size - total % size, chunks.shape[1]), dtype=np.float32)])
        started = time.perf_counter()
        parts = [session.run(['embedding'], {input_name: chunks[i:i + size]})[0] for i in range(0, len(chunks), size)]
        per_track.append(time.perf_counter() - started)
        windows += total
        np.save(out / f'{index}.npy', np.concatenate(parts)[:total].astype(np.float32))
    print(json.dumps({'load_s': load, 'track_s': per_track, 'windows': windows, 'batch': size,
                      'runtime': onnxruntime.__version__}))


def run_worker(python, name, precision, provider, count, threads):
    command = [str(python), __file__, 'worker', name, precision, provider, str(count), str(threads)]
    result = subprocess.run(command, capture_output=True, text=True, cwd=REPO)
    lines = [line for line in result.stdout.splitlines() if line.startswith('{')]
    if result.returncode or not lines:
        return {'error': (result.stderr.strip().splitlines() or ['no output'])[-1][:300]}
    return json.loads(lines[-1])


# ---- 4. quality: int8 against fp32 ---------------------------------------------------------------------------

def unit(matrix):
    return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)


def compare(name, count, provider='cpu', k=10):
    """Window cosine similarity int8 vs fp32, and how many of each window's k nearest windows (in other tracks)
    stay the same; plus each track's closest other track (mean vector)."""
    fp32 = [np.load(WORK / 'embeddings' / f'{name}-fp32-{provider}' / f'{i}.npy') for i in range(count)]
    int8 = [np.load(WORK / 'embeddings' / f'{name}-int8-{provider}' / f'{i}.npy') for i in range(count)]
    cosines = np.concatenate([np.sum(unit(a) * unit(b), axis=1) for a, b in zip(fp32, int8)])
    track_of = np.concatenate([np.full(len(a), i) for i, a in enumerate(fp32)])

    def neighbours(windows):
        vectors = unit(np.concatenate(windows))
        similarity = vectors @ vectors.T
        similarity[track_of[:, None] == track_of[None, :]] = -np.inf  # only windows of other tracks
        return np.argsort(-similarity, axis=1)[:, :k]

    a, b = neighbours(fp32), neighbours(int8)
    overlap = np.mean([len(set(x) & set(y)) / k for x, y in zip(a, b)])

    def closest_tracks(windows):
        means = unit(np.stack([w.mean(axis=0) for w in windows]))
        similarity = means @ means.T
        np.fill_diagonal(similarity, -np.inf)
        return similarity.argmax(axis=1)

    same_closest = int(np.sum(closest_tracks(fp32) == closest_tracks(int8)))
    return {'cosine_mean': float(cosines.mean()), 'cosine_min': float(cosines.min()),
            f'top{k}_overlap': float(overlap), 'same_closest_track': f'{same_closest}/{count}'}


# ---- 5. what the user sees: the app's percentages, fp32 vs int8 ------------------------------------------------

PROMPTS = [  # the research notebook's prompts (research/experiments/clap/text_search.ipynb)
    'dark rolling drum and bass with a heavy reese bassline', 'hypnotic psychedelic techno with swirling acid synths',
    'dark warehouse rave, pounding kick and distorted acid 303 line',
    'euphoric trance with rising synth arpeggios and a big build-up',
    'calm downtempo track with warm pads and soft piano', 'dreamy ambient electronica with gentle melodies',
    'slow, mellow trip-hop beat with a jazzy feel', 'funky breakbeat with a groovy bassline and chopped drum breaks',
    'big beat with funky samples, scratching and a bouncy break',
    'nu-skool breaks with a rolling bassline and energetic drums', 'female vocal house track',
    'aggressive distorted electro']


def points(scores_fp32, scores_int8):
    """Differences in the app's percentage points (round(cosine x 100)) and how often they reach 2 / 5 / 10."""
    a, b = np.round(np.asarray(scores_fp32) * 100), np.round(np.asarray(scores_int8) * 100)
    difference = np.abs(a - b)
    return {'pairs': int(difference.size), 'mean_pp': float(difference.mean()), 'max_pp': float(difference.max()),
            'pairs_2pp_or_more': float(np.mean(difference >= 2)), 'pairs_5pp_or_more': float(np.mean(difference >= 5)),
            'pairs_10pp_or_more': float(np.mean(difference >= 10))}


def percentages(count, provider='cpu'):
    """Description search (LAION: prompt vs track, as core/text_search.py) and closest matches (CNN14: track vs
    track on centred mean+std vectors, as core/similarity.py), fp32 against int8."""
    from songselector.core.similarity import track_vectors
    from songselector.core.text_search import TextEncoder, clap_track_vector

    def load(name, precision):
        return [np.load(WORK / 'embeddings' / f'{name}-{precision}-{provider}' / f'{i}.npy') for i in range(count)]

    encoder = TextEncoder(LAION_CLAP, FP32_FOLDER)  # the text side is not quantized
    queries = np.stack([encoder.encode(prompt) for prompt in PROMPTS])
    text = {}
    for precision in ('fp32', 'int8'):
        tracks = np.stack([clap_track_vector(windows) for windows in load('laion', precision)])
        text[precision] = queries @ tracks.T  # (prompts, tracks)
    top3_same = np.mean([list(np.argsort(-a)[:3]) == list(np.argsort(-b)[:3])
                         for a, b in zip(text['fp32'], text['int8'])])
    examples = []
    for p in range(len(PROMPTS)):  # each prompt's best track: fp32 % -> int8 %
        best = int(np.argmax(text['fp32'][p]))
        examples.append((PROMPTS[p], round(text['fp32'][p, best] * 100), round(text['int8'][p, best] * 100)))
    tracks_matrix = {}
    for precision in ('fp32', 'int8'):
        vectors = track_vectors(load('cnn14', precision))
        similarity = vectors @ vectors.T
        tracks_matrix[precision] = similarity[np.triu_indices(count, 1)]  # every pair once
    return {'text_search': {**points(text['fp32'], text['int8']), 'top3_order_same': float(top3_same),
                            'examples': examples},
            'closest_matches': points(tracks_matrix['fp32'], tracks_matrix['int8'])}


# ---- 6. everything -------------------------------------------------------------------------------------------

def run(folder, count, seed, threads):
    missing = [str(model_file(name, 'int8')) for name in MODELS if not model_file(name, 'int8').is_file()]
    if missing:
        sys.exit('Run the quantize step first; missing: ' + ', '.join(missing))
    durations, decode_seconds = decode(folder, count, seed)
    audio_minutes = sum(durations) / 60
    print(f'{len(durations)} tracks, {audio_minutes:.1f} min of audio, decoding {sum(decode_seconds):.1f} s '
          f'(both sample rates)')
    pythons = {'cpu': APP_PYTHON, 'dml': APP_PYTHON, 'cuda': CUDA_PYTHON}
    timings = {}
    for name in MODELS:
        for provider, python in pythons.items():
            for precision in ('fp32', 'int8'):
                result = run_worker(python, name, precision, provider, len(durations), threads)
                timings[(name, provider, precision)] = result
                shown = result.get('error') or f"{sum(result['track_s']):.1f} s, load {result['load_s']:.1f} s"
                print(f'{name:6} {provider:4} {precision}: {shown}')
    quality = {name: compare(name, len(durations)) for name in MODELS}
    report(durations, decode_seconds, timings, quality, threads, seed)
    add_percentages(len(durations))


def add_percentages(count):
    """Append the app's percentages, fp32 vs int8, to today's report."""
    views = percentages(count)
    text, tracks = views['text_search'], views['closest_matches']

    def row(label, v):
        return (f'| {label} | {v["pairs"]} | {v["mean_pp"]:.2f} | {v["max_pp"]:.0f} | {v["pairs_2pp_or_more"] * 100:.0f} % | '
                f'{v["pairs_5pp_or_more"] * 100:.0f} % | {v["pairs_10pp_or_more"] * 100:.0f} % |')

    lines = ['', '## The percentages the app shows, fp32 vs int8 (CPU embeddings)', '',
             'Description search: LAION, each prompt against each track (round(cosine x 100), as the List shows it); '
             'the text encoder is the same fp32 model for both. Closest matches: CNN14, each pair of tracks (centred '
             'mean+std vectors, as the map).', '',
             '| Shown in the app | Pairs | Mean difference (points) | Largest | >= 2 points | >= 5 points | >= 10 points |',
             '|---|---|---|---|---|---|---|', row('Description search (LAION)', text),
             row('Closest matches (CNN14)', tracks), '',
             f'Same top 3 tracks, in the same order, for {text["top3_order_same"] * 100:.0f} % of the prompts.', '',
             '| Prompt | Its best track: fp32 | int8 |', '|---|---|---|']
    lines += [f'| {prompt} | {a} % | {b} % |' for prompt, a, b in text['examples']]
    path = RESULTS / f'{date.today()}_int8_benchmark.md'
    with path.open('a', encoding='utf-8') as handle:
        handle.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


def report(durations, decode_seconds, timings, quality, threads, seed):
    RESULTS.mkdir(parents=True, exist_ok=True)
    minutes = sum(durations) / 60
    names = {'cpu': f'CPU ({threads} threads)', 'dml': 'GPU, DirectML', 'cuda': 'GPU, CUDA'}
    lines = [f'# int8 vs fp32: audio to embeddings ({date.today()})', '',
             f'{len(durations)} random tracks (seed {seed}), {minutes:.1f} min of audio; decoding (both rates, once): '
             f'{sum(decode_seconds):.1f} s, not included below. Machine: {platform.processor() or platform.machine()}, '
             f'{os.cpu_count()} logical cores; GPU GeForce GTX 1650 Ti (4 GB). Times: all windows of all tracks, '
             'after a warm-up call; batch sizes as in the app.', '',
             '| Model | Device | fp32 | int8 | int8 speed-up | fp32 per audio minute | int8 per audio minute |',
             '|---|---|---|---|---|---|---|']
    for name, spec in MODELS.items():
        for provider in ('cpu', 'dml', 'cuda'):
            a, b = timings.get((name, provider, 'fp32'), {}), timings.get((name, provider, 'int8'), {})
            if 'track_s' not in a or 'track_s' not in b:
                error = a.get('error') or b.get('error') or 'not run'
                lines.append(f'| {spec.name} | {names[provider]} | {error} | | | | |')
                continue
            ta, tb = sum(a['track_s']), sum(b['track_s'])
            lines.append(f'| {spec.name} | {names[provider]} (batch {a["batch"]}) | {ta:.1f} s | {tb:.1f} s | '
                         f'{ta / tb:.2f}x | {ta / minutes:.2f} s | {tb / minutes:.2f} s |')
    lines += ['', '| Model | File size fp32 / int8 | Window cosine int8 vs fp32 (mean / min) | '
              'Top-10 neighbour windows kept | Same closest track |', '|---|---|---|---|---|']
    for name, spec in MODELS.items():
        q = quality[name]
        sizes = f'{model_file(name, "fp32").stat().st_size / 1e6:.0f} / {model_file(name, "int8").stat().st_size / 1e6:.0f} MB'
        lines.append(f'| {spec.name} | {sizes} | {q["cosine_mean"]:.4f} / {q["cosine_min"]:.4f} | '
                     f'{q["top10_overlap"] * 100:.0f} % | {q["same_closest_track"]} |')
    text = '\n'.join(lines) + '\n'
    path = RESULTS / f'{date.today()}_int8_benchmark.md'
    path.write_text(text, encoding='utf-8')
    raw = {f'{n}|{p}|{q}': value for (n, p, q), value in timings.items()}
    path.with_suffix('.json').write_text(json.dumps({'durations_s': durations, 'decode_s': decode_seconds,
                                                     'timings': raw, 'quality': quality}, indent=1), encoding='utf-8')
    print('\n' + text + f'\nWritten: {path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='step', required=True)
    sub.add_parser('quantize')
    sub.add_parser('percentages').add_argument('--count', type=int, default=10)
    runner = sub.add_parser('run')
    runner.add_argument('--tracks', required=True, help='music folder to pick tracks from')
    runner.add_argument('--count', type=int, default=10)
    runner.add_argument('--seed', type=int, default=20261120)
    runner.add_argument('--threads', type=int, default=max(1, (os.cpu_count() or 2) // 2))  # as the app
    work = sub.add_parser('worker')
    for argument in ('name', 'precision', 'provider'):
        work.add_argument(argument)
    work.add_argument('count', type=int)
    work.add_argument('threads', type=int)
    args = parser.parse_args()
    if args.step == 'quantize':
        quantize()
    elif args.step == 'worker':
        worker(args.name, args.precision, args.provider, args.count, args.threads)
    elif args.step == 'percentages':  # after a run: from the embeddings it saved
        add_percentages(args.count)
    else:
        run(args.tracks, args.count, args.seed, args.threads)


if __name__ == '__main__':
    main()

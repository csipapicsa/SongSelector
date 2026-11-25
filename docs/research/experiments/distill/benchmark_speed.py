"""Phase 0: is a small student really cheaper on the CPU than the AllMusicCaps audio model, end to end?

Speed does not depend on what a network has learned, so the students run with random weights (students.py): the
question can be answered before any training. Everything goes through onnxruntime's CPU provider with the app's
session options, the way a user without a GPU would run it.

Each (model, thread count) runs in its own process, so thread settings and memory figures do not leak between runs.
A worker measures:
  load      session creation time, memory after loading
  window    one 10 s window: batch 1 (median and p95) and batch 8 (per window)
  tracks    real tracks from the library: decode (the app's decoder) once, then embed every window and the 6
            sampled windows; wall time and CPU time (all threads together: the load on the machine)
  memory    peak working set of the process

    .research_cache\\venv-distill\\Scripts\\python docs\\research\\experiments\\distill\\students.py
    .research_cache\\venv-distill\\Scripts\\python docs\\research\\experiments\\distill\\benchmark_speed.py

Writes docs/research/experiments/results/<date>_distill_phase0_speed.json (no track paths in it).
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    REPO,
    RESULTS,
    SAMPLED_WINDOWS,
    TEACHER_ONNX,
    WINDOW,
    WORK,
    decode,
    mlflow_experiment,
    sampled_indices,
    teacher_tracks,
    windows_of,
)

ONNX_DIR = WORK / 'onnx'
STUDENT_NAMES = ['mfcc40-mlp', 'cnn4-small-64', 'cnn4-64', 'mnv3s-128']
LIBRARY_TRACKS = 5000   # the size of the DJ's library, to turn seconds per track into hours


def model_path(name):
    return TEACHER_ONNX if name == 'teacher' else ONNX_DIR / f'{name}.onnx'


# ---- Worker: one model, one thread count ------------------------------------------------------------------------

def session(path, threads):
    """A CPU session with the app's options (core/embeddings.py OnnxEmbedder._options)."""
    import onnxruntime
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.enable_mem_pattern = False
    options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
    return onnxruntime.InferenceSession(str(path), options, providers=['CPUExecutionProvider'])


def embed(sess, windows, batch):
    name = sess.get_inputs()[0].name
    for start in range(0, len(windows), batch):
        sess.run(None, {name: windows[start:start + batch]})


def timed_ms(function, repeats, warmup=3):
    for _ in range(warmup):
        function()
    times = []
    for _ in range(repeats):
        started = time.perf_counter()
        function()
        times.append((time.perf_counter() - started) * 1000)
    return times


def cpu_seconds(process):
    times = process.cpu_times()
    return times.user + times.system


def worker(name, threads, tracks, batch, repeats):
    import onnxruntime
    import psutil
    process = psutil.Process()
    started = time.perf_counter()
    sess = session(model_path(name), threads)
    result = {'model': name, 'threads': threads, 'batch': batch, 'onnxruntime': onnxruntime.__version__,
              'load_s': time.perf_counter() - started, 'rss_after_load_mb': process.memory_info().rss / 1e6,
              'onnx_mb': model_path(name).stat().st_size / 1e6}

    rng = np.random.default_rng(0)
    one = rng.uniform(-0.3, 0.3, (1, WINDOW)).astype(np.float32)
    eight = rng.uniform(-0.3, 0.3, (8, WINDOW)).astype(np.float32)
    b1 = timed_ms(lambda: embed(sess, one, 1), repeats)
    result['window_ms_b1_median'] = statistics.median(b1)
    result['window_ms_b1_p95'] = float(np.percentile(b1, 95))
    result['window_ms_b8'] = statistics.median(timed_ms(lambda: embed(sess, eight, 8), max(3, repeats // 4))) / 8

    per_track = []
    for path in tracks:
        cpu, started = cpu_seconds(process), time.perf_counter()
        audio = decode(path)
        decode_s, decode_cpu_s = time.perf_counter() - started, cpu_seconds(process) - cpu
        windows = windows_of(audio)
        sampled = np.ascontiguousarray(windows[sampled_indices(len(windows))])
        row = {'minutes': len(audio) / 60 / 24000, 'windows': len(windows), 'decode_s': decode_s,
               'decode_cpu_s': decode_cpu_s}
        for mode, chosen in (('all', windows), ('sampled', sampled)):
            cpu, started = cpu_seconds(process), time.perf_counter()
            embed(sess, chosen, batch)
            row[f'embed_{mode}_s'] = time.perf_counter() - started
            row[f'embed_{mode}_cpu_s'] = cpu_seconds(process) - cpu
        per_track.append(row)
    result['tracks'] = per_track
    info = process.memory_info()
    result['rss_peak_mb'] = getattr(info, 'peak_wset', info.rss) / 1e6
    print(json.dumps(result))


# ---- Main: pick tracks, run every worker, summarise --------------------------------------------------------------

def pick_tracks(count, seed):
    """Random tracks the app embedded with AllMusicCaps, 2-12 minutes long (12-72 windows), that still exist."""
    candidates = teacher_tracks(min_windows=12, max_windows=72)
    random.Random(seed).shuffle(candidates)
    return [str(path) for path, _ in candidates if path.is_file()][:count]


def summarise(run):
    """Per track normalised to 6 minutes (decode and 'every window' scale with length; 6 windows do not)."""
    tracks = run['tracks']
    minutes = sum(t['minutes'] for t in tracks)

    def per_min(key):
        return sum(t[key] for t in tracks) / minutes

    def per_track(key):
        return statistics.mean(t[key] for t in tracks)

    s = {
        'decode_s_per_6min': 6 * per_min('decode_s'),
        'embed_all_s_per_6min': 6 * per_min('embed_all_s'),
        'embed_sampled_s_per_track': per_track('embed_sampled_s'),
        'cpu_all_s_per_6min': 6 * (per_min('decode_cpu_s') + per_min('embed_all_cpu_s')),
        'cpu_sampled_s_per_6min': 6 * per_min('decode_cpu_s') + per_track('embed_sampled_cpu_s'),
    }
    s['e2e_all_s_per_6min'] = s['decode_s_per_6min'] + s['embed_all_s_per_6min']
    s['e2e_sampled_s_per_6min'] = s['decode_s_per_6min'] + s['embed_sampled_s_per_track']
    s['library_all_h'] = s['e2e_all_s_per_6min'] * LIBRARY_TRACKS / 3600
    s['library_sampled_h'] = s['e2e_sampled_s_per_6min'] * LIBRARY_TRACKS / 3600
    s['real_time_factor_all'] = s['e2e_all_s_per_6min'] / 360
    return s


def cpu_name():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0')
        return winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()
    except OSError:
        return platform.processor()


def git_commit():
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=REPO, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ''


def print_table(runs):
    print(f"\n{'model':15s} {'thr':>3s} {'MB':>6s} {'ms/win b1':>9s} {'b8':>6s} | per 6-min track:"
          f" {'decode':>6s} {'all':>6s} {'6 win':>6s} | {'CPU-s all':>9s} {'6 win':>6s} | {'peak MB':>7s}")
    for run in runs:
        s = run['summary']
        print(f"{run['model']:15s} {run['threads']:3d} {run['onnx_mb']:6.1f} {run['window_ms_b1_median']:9.1f} "
              f"{run['window_ms_b8']:6.1f} |                 {s['decode_s_per_6min']:6.2f} {s['e2e_all_s_per_6min']:6.2f} "
              f"{s['e2e_sampled_s_per_6min']:6.2f} | {s['cpu_all_s_per_6min']:9.2f} {s['cpu_sampled_s_per_6min']:6.2f} | "
              f"{run['rss_peak_mb']:7.0f}")


RUN_METRICS = ['load_s', 'rss_after_load_mb', 'rss_peak_mb', 'onnx_mb', 'window_ms_b1_median', 'window_ms_b1_p95',
               'window_ms_b8']


def onnx_params_m(path):
    """Parameters in millions: the weights stored in the ONNX file (None if the file is not there)."""
    import onnx
    if not Path(path).is_file():
        return None
    graph = onnx.load(str(path), load_external_data=False).graph
    return sum(int(np.prod(tensor.dims)) for tensor in graph.initializer) / 1e6


def log_to_mlflow(report, json_path):
    """One parent run per benchmark (setup, machine, the JSON as artifact) with a nested run per (model, threads):
    the parent answers "which benchmark", the children are the rows to compare in the MLflow UI."""
    mlflow = mlflow_experiment('distill-speed')
    setup, machine = report['setup'], report['machine']
    tags = {'phase': '0', 'git_commit': setup['git_commit'], 'cpu': machine['cpu']}
    with mlflow.start_run(run_name=f"phase0-{report['date']}", tags=tags, description=report['question']) as parent:
        mlflow.log_params({key: value for key, value in setup.items() if key != 'git_commit'})
        mlflow.log_params({f'machine.{key}': value for key, value in machine.items()})
        mlflow.log_artifact(str(json_path))
        for run in report['runs']:
            role = 'teacher' if run['model'] == 'teacher' else 'student'
            with mlflow.start_run(run_name=f"{run['model']}-t{run['threads']}", nested=True, tags={**tags, 'role': role}):
                params = {'model': run['model'], 'threads': run['threads'], 'batch': run['batch'],
                          'onnxruntime': run['onnxruntime']}
                size = onnx_params_m(model_path(run['model']))
                if size is not None:
                    params['params_m'] = round(size, 3)
                mlflow.log_params(params)
                mlflow.log_metrics({**{key: run[key] for key in RUN_METRICS}, **run['summary']})
    print(f'Logged to MLflow: experiment distill-speed, run {parent.info.run_id}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--models', nargs='+', default=['teacher', *STUDENT_NAMES])
    parser.add_argument('--threads', type=int, nargs='+', default=[1, 4], help='4 is the app default here')
    parser.add_argument('--count', type=int, default=10, help='real tracks per worker')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--batch', type=int, default=8, help='windows per call when embedding tracks')
    parser.add_argument('--repeats', type=int, default=20, help='timed batch-1 calls per model')
    parser.add_argument('--out', type=Path, default=RESULTS / f'{date.today()}_distill_phase0_speed.json')
    parser.add_argument('--worker', nargs=2, metavar=('MODEL', 'THREADS'), help=argparse.SUPPRESS)
    parser.add_argument('--tracks-file', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--no-mlflow', action='store_true', help='only write the JSON')
    parser.add_argument('--log-json', type=Path, help='log an earlier results JSON to MLflow, without measuring')
    args = parser.parse_args()
    if args.worker:
        tracks = json.loads(args.tracks_file.read_text(encoding='utf-8'))
        return worker(args.worker[0], int(args.worker[1]), tracks, args.batch, args.repeats)
    if args.log_json:
        return log_to_mlflow(json.loads(args.log_json.read_text(encoding='utf-8')), args.log_json)

    missing = [name for name in args.models if not model_path(name).is_file()]
    if missing:
        sys.exit(f'Missing ONNX files for {missing}: run students.py first (teacher: {TEACHER_ONNX}).')
    tracks = pick_tracks(args.count, args.seed)
    tracks_file = WORK / 'phase0_tracks.json'    # local only: the paths stay out of the committed results
    tracks_file.parent.mkdir(parents=True, exist_ok=True)
    tracks_file.write_text(json.dumps(tracks), encoding='utf-8')
    for track in tracks:   # warm the OS file cache: otherwise the first worker alone pays for reading the disk
        Path(track).read_bytes()

    runs = []
    for name in args.models:
        for threads in args.threads:
            print(f'{name}, {threads} thread(s) ...', flush=True)
            command = [sys.executable, __file__, '--worker', name, str(threads), '--tracks-file', str(tracks_file),
                       '--batch', str(args.batch), '--repeats', str(args.repeats)]
            output = subprocess.run(command, capture_output=True, text=True, check=True).stdout
            run = json.loads(output.strip().splitlines()[-1])
            run['summary'] = summarise(run)
            runs.append(run)

    import onnxruntime
    import psutil
    report = {
        'date': str(date.today()),
        'question': 'Phase 0 of the AllMusicCaps distillation: CPU cost of the teacher vs untrained students, '
                    'end to end (decode + model), every window and 6 sampled windows.',
        'machine': {'cpu': cpu_name(), 'logical_cpus': os.cpu_count(),
                    'ram_gb': round(psutil.virtual_memory().total / 1e9, 1), 'os': platform.platform(),
                    'python': platform.python_version(), 'onnxruntime': onnxruntime.__version__},
        'setup': {'tracks': len(tracks), 'seed': args.seed, 'batch': args.batch, 'repeats_b1': args.repeats,
                  'provider': 'CPUExecutionProvider, app session options', 'sampled_windows': SAMPLED_WINDOWS,
                  'decode': 'app decoder (core/embeddings.load_audio_rates), 24 kHz', 'git_commit': git_commit(),
                  'students': 'random weights (speed only)'},
        'runs': runs,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1), encoding='utf-8')
    print_table(runs)
    print(f'\nWrote {args.out}')
    if not args.no_mlflow:
        log_to_mlflow(report, args.out)


if __name__ == '__main__':
    main()

"""Benchmark: is CNN14 faster on the CPU once it no longer runs as Python (PyTorch)?

Not part of the app and skipped unless configured. It decodes random tracks once
(as the app does), then runs the same audio through four CPU backends, each in its
own process with the same number of threads and one 5 s chunk per call:

  torch        PyTorch eager: Python calls every layer (the original pipeline)
  torchscript  the same model traced and frozen into a graph: no Python per layer
  onnx-noopt   the exported cnn14.onnx in onnxruntime (C++), graph optimisations off
  onnx         onnxruntime as the app runs it (all graph optimisations)

It checks that all four give the same embeddings and prints the times.

Environment:
  TKC_CNN14_ONNX       cnn14.onnx
  TKC_TORCH_PYTHON     a python.exe with torch and panns_inference installed
  TKC_BENCH_TRACKS     a music folder or a library.sqlite (opened read-only)
  TKC_TORCH_CHECKPOINT optional, default %USERPROFILE%\\panns_data\\Cnn14_mAP=0.431.pth
  TKC_BENCH_COUNT      optional, tracks to pick (default 10)
  TKC_BENCH_THREADS    optional, default half the cores as in the app
  TKC_BENCH_SEED       optional, to pick the same tracks again

Run (the report is printed, hence -s):
  .\\scripts\\test.ps1 tests\\test_inference_speed.py -s
"""
import json
import os
import random
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from traktor_key_calculator.core.embeddings import CHUNK_SECONDS, SAMPLE_RATE, load_audio, split_chunks

WORKER = Path(__file__).with_name('benchmarks') / 'cnn14_backends.py'
AUDIO_SUFFIXES = {'.mp3', '.flac', '.wav', '.aif', '.aiff', '.ogg'}
REQUIRED = ('TKC_CNN14_ONNX', 'TKC_TORCH_PYTHON', 'TKC_BENCH_TRACKS')


def candidate_tracks(source):
    source = Path(source)
    if source.suffix == '.sqlite':
        with sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True) as connection:
            paths = [Path(row[0]) for row in connection.execute('SELECT file_path FROM tracks')]
    else:
        paths = list(source.rglob('*'))
    return sorted(path for path in paths if path.suffix.lower() in AUDIO_SUFFIXES and path.is_file())


@unittest.skipUnless(all(os.environ.get(name) for name in REQUIRED), 'set ' + ', '.join(REQUIRED) + ' to run')
class InferenceSpeedTests(unittest.TestCase):
    def test_cnn14_on_the_cpu_pytorch_vs_compiled_vs_onnxruntime(self):
        count = int(os.environ.get('TKC_BENCH_COUNT', 10))
        threads = int(os.environ.get('TKC_BENCH_THREADS') or max(1, (os.cpu_count() or 2) // 2))
        seed = int(os.environ.get('TKC_BENCH_SEED') or random.randrange(10 ** 6))
        checkpoint = os.environ.get('TKC_TORCH_CHECKPOINT') or str(Path.home() / 'panns_data' / 'Cnn14_mAP=0.431.pth')
        candidates = candidate_tracks(os.environ['TKC_BENCH_TRACKS'])
        random.Random(seed).shuffle(candidates)

        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            tracks, decode_seconds = {}, []
            for path in candidates:
                started = time.perf_counter()
                try:
                    audio = load_audio(path)
                except Exception:
                    continue  # unreadable file: take the next one
                if len(audio) < SAMPLE_RATE:
                    continue
                decode_seconds.append(time.perf_counter() - started)
                tracks[f'{len(tracks):02d}'] = (path, split_chunks(audio))
                if len(tracks) == count:
                    break
            self.assertEqual(len(tracks), count, 'not enough readable tracks')
            np.savez(folder / 'chunks.npz', **{key: chunks for key, (_, chunks) in tracks.items()})

            results, outputs = {}, {}
            for backend, python, model in (('torch', os.environ['TKC_TORCH_PYTHON'], checkpoint),
                                           ('torchscript', os.environ['TKC_TORCH_PYTHON'], checkpoint),
                                           ('onnx-noopt', sys.executable, os.environ['TKC_CNN14_ONNX']),
                                           ('onnx', sys.executable, os.environ['TKC_CNN14_ONNX'])):
                out = folder / f'{backend}.npz'
                run = subprocess.run([python, str(WORKER), backend, model, str(folder / 'chunks.npz'), str(out),
                                      str(threads)], capture_output=True, text=True, timeout=3600)
                self.assertEqual(run.returncode, 0, f'{backend} failed:\n{run.stderr[-3000:]}')
                results[backend] = json.loads(run.stdout.strip().splitlines()[-1])
                with np.load(out) as data:
                    outputs[backend] = {key: data[key] for key in data.files}

        reference = outputs['torch']
        differences = {}
        for backend, embeddings in outputs.items():
            for key, (_, chunks) in tracks.items():
                self.assertEqual(embeddings[key].shape, (len(chunks), 2048), backend)
            differences[backend] = max(float(np.abs(embeddings[key] - reference[key]).max()) for key in tracks)
            self.assertLess(differences[backend], 1e-3, f'{backend} gives other embeddings than PyTorch')

        audio_minutes = sum(len(chunks) for _, chunks in tracks.values()) * CHUNK_SECONDS / 60
        baseline = sum(results['torch']['seconds'])
        lines = [f'\nCNN14 on the CPU: {count} random tracks (seed {seed}), {audio_minutes:.1f} min of audio, '
                 f'{threads} threads, 1 chunk per call',
                 f'Decoding (soundfile + soxr, as the app): {sum(decode_seconds):.1f} s in total',
                 f'{"backend":<12} {"load s":>7} {"model s":>8} {"s/track":>8} {"s/audio min":>12} '
                 f'{"vs torch":>9} {"max diff":>9}']
        for backend, result in results.items():
            total = sum(result['seconds'])
            lines.append(f'{backend:<12} {result["load_seconds"]:>7.1f} {total:>8.1f} {total / count:>8.2f} '
                         f'{total / audio_minutes:>12.2f} {baseline / total:>8.2f}x {differences[backend]:>9.1e}')
        lines.append('Per track, model s: ' + ', '.join(
            f'{key}: ' + '/'.join(f'{results[b]["seconds"][int(key)]:.1f}' for b in results) for key in tracks))
        print('\n'.join(lines))


if __name__ == '__main__':
    unittest.main(verbosity=2)

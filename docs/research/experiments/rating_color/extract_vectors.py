"""Extract one vector per track for the small models, for every track that has a CNN14 embedding.

Run with the app's .venv (GPU through DirectML):
    ..\\..\\..\\..\\.venv\\Scripts\\python extract_vectors.py --models musicnn,discogs_effnet,openl3 --workers 3
Resumable: raw vectors are kept in .research_cache/vectors/<model>_raw.npz and saved every 100 tracks.
At the end each model's vectors are centred and made unit length (as the app does for CNN14) and saved
as .research_cache/vectors/<model>.npz, which `evaluate.py --model <model>` reads.
Also writes timings (decode, per model) to .research_cache/vectors/timings.json.
"""
import argparse
import json
import multiprocessing as mp
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import models
from common import CACHE, Vectors, save_vectors

MAX_SECONDS = 600  # longer files (mixes) are cut here; 99 % of tracks are shorter
_models = {}


def _init(names):
    for name in names:
        _models[name] = models.ALL[name]()


def _work(job):
    key, path = job
    try:
        timings = {}
        start = time.perf_counter()
        rates = sorted({m.rate for m in _models.values()})
        audio = models.decode(path, rates)
        audio = {rate: signal[:rate * MAX_SECONDS] for rate, signal in audio.items()}
        timings['decode'] = time.perf_counter() - start
        timings['seconds'] = len(audio[rates[0]]) / rates[0]
        vectors = {}
        for name, model in _models.items():
            windows, spent = models.timed(model.windows, audio)
            vectors[name] = models.pool(windows)
            timings[name] = spent
        return key, vectors, timings, None
    except Exception as error:  # a broken file must not stop the run
        return key, None, None, f'{type(error).__name__}: {error}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--models', default='musicnn,discogs_effnet,openl3')
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--limit', type=int, default=0, help='only the first N tracks (a test run)')
    args = parser.parse_args()
    names = args.models.split(',')

    snapshot = CACHE / 'snapshot'
    wanted = {key for (key,) in sqlite3.connect(snapshot / 'embeddings.sqlite').execute(
        'SELECT path_key FROM embeddings WHERE data IS NOT NULL')}
    paths = {key: path for key, path in sqlite3.connect(snapshot / 'library.sqlite').execute(
        'SELECT path_key, file_path FROM tracks') if key in wanted and Path(path).exists()}
    # Labelled tracks first (rating or colour set): a partial run is already usable for evaluation.
    labelled = {key for (key,) in sqlite3.connect(snapshot / 'library.sqlite').execute(
        'SELECT path_key FROM tracks WHERE rating IS NOT NULL OR color > 0')}
    # Random order within the two groups, so any partial run is a fair sample of the library.
    shuffled = sorted(paths)
    np.random.default_rng(0).shuffle(shuffled)
    order = sorted(shuffled, key=lambda key: key not in labelled)  # stable: keeps the random order
    if args.limit:
        order = order[:args.limit]

    raw_file = {name: CACHE / 'vectors' / f'{name}_raw.npz' for name in names}
    (CACHE / 'vectors').mkdir(parents=True, exist_ok=True)
    raw = {}
    for name in names:
        raw[name] = {}
        if raw_file[name].exists() and not args.limit:
            data = np.load(raw_file[name])
            raw[name] = dict(zip(data['keys'].tolist(), data['matrix']))
    done = set.intersection(*(set(raw[name]) for name in names)) if all(raw.values()) else set()
    todo = [(key, paths[key]) for key in order if key not in done]
    print(f'{len(order)} tracks, {len(done)} already done, {len(todo)} to do, models {names}, workers {args.workers}')

    def save_raw():
        if args.limit:
            return
        for name in names:
            np.savez(raw_file[name], keys=np.array(list(raw[name])), matrix=np.stack(list(raw[name].values())))

    timings, errors, start = [], [], time.time()
    context = mp.get_context('spawn')
    with context.Pool(args.workers, initializer=_init, initargs=(names,)) as pool:
        for count, (key, vectors, spent, error) in enumerate(pool.imap_unordered(_work, todo, chunksize=2), 1):
            if error:
                errors.append((key, error))
                continue
            for name in names:
                raw[name][key] = vectors[name]
            timings.append(spent)
            if count % 100 == 0:
                save_raw()
                rate = count / (time.time() - start)
                print(f'  {count}/{len(todo)} ({rate:.2f} tracks/s, about {(len(todo) - count) / rate / 60:.0f} min left, '
                      f'{len(errors)} failed)', flush=True)
    save_raw()
    if args.limit:
        pass
    summary = {name: float(np.mean([t[name] / t['seconds'] * 360 for t in timings])) for name in names}
    summary['decode'] = float(np.mean([t['decode'] / t['seconds'] * 360 for t in timings]))
    print('seconds per 6-minute track with', args.workers, 'workers sharing the machine:', json.dumps(summary, indent=1))
    if not args.limit:
        (CACHE / 'vectors' / 'timings.json').write_text(json.dumps(summary, indent=1))
        for name in names:  # centred, unit length, like the app's track vectors
            keys = sorted(raw[name])
            matrix = np.stack([raw[name][k] for k in keys])
            matrix = matrix - matrix.mean(0)
            matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-9)
            save_vectors(name, Vectors(keys, matrix.astype(np.float32)))
            print(f'saved {name}: {matrix.shape}')
    if errors:
        print(f'{len(errors)} failed, e.g.', errors[:3])


if __name__ == '__main__':
    main()

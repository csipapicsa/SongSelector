"""CLAP embeddings for a test set of the library, for trying free-text search in text_search.ipynb.

Test set: tracks with a Traktor rating of 4-5 and a Traktor colour (the DJ's "good, sorted" tracks), about 1,000.
Every window of every track is embedded and stored (not just a track average), so the notebook can compare
"whole track" with "a few sampled windows" and play the part of a track that matched a prompt.

How it runs (research only; the app is not touched):
- the library is read from a copy (SQLite backup API, safe while the app is open); results go to .research_cache/clap/
- each track is decoded ONCE and resampled to every model's rate; decoding of the next tracks runs in parallel
  threads (libsndfile and soxr release the GIL) while the GPU embeds the current one
- all models run in this one process, only their audio halves on the GPU (fits a 4 GB card)
- resumable per model: run it again and it continues where it stopped; tracks in a fixed random order, so partial
  results are a fair sample. Below-normal priority, so the laptop stays usable.

    .research_cache\\venv-clap\\Scripts\\python docs\\research\\experiments\\clap\\extract_embeddings.py --app-data dist

Output per model: .research_cache/clap/<model>.sqlite, table windows(path_key, n, dim, window_s, vectors float32).
"""
import argparse
import json
import os
import random
import sqlite3
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_cpu import BATCH, load_model, windows_of  # noqa: E402

REPO = Path(__file__).resolve().parents[4]
OUT = REPO / '.research_cache' / 'clap'
DEFAULT_MODELS = ['laion-unfused', 'ms-2023', 'laion-music']


def copy_library(app_data):
    """A consistent copy of the app's library.sqlite, made through SQLite's backup API (safe while the app runs)."""
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / 'library.sqlite'
    source = sqlite3.connect(f'file:{Path(app_data) / "library.sqlite"}?mode=ro', uri=True)
    with sqlite3.connect(target) as copy:
        source.backup(copy)
    source.close()
    return target


def select_tracks(library, seed=0):
    """Rating 4-5 and a colour 1-7, file present; in a fixed random order."""
    with sqlite3.connect(f'file:{library}?mode=ro', uri=True) as connection:
        rows = connection.execute('SELECT path_key, file_path FROM tracks WHERE rating >= 4 AND color BETWEEN 1 AND 7 '
                                  'ORDER BY path_key').fetchall()
    rows = [(key, path) for key, path in rows if os.path.isfile(path)]
    random.Random(seed).shuffle(rows)
    return rows


def open_store(model):
    connection = sqlite3.connect(OUT / f'{model}.sqlite', check_same_thread=False)
    connection.execute('CREATE TABLE IF NOT EXISTS windows (path_key TEXT PRIMARY KEY, n INTEGER, dim INTEGER, '
                       'window_s REAL, vectors BLOB)')
    connection.execute('CREATE TABLE IF NOT EXISTS errors (path_key TEXT PRIMARY KEY, message TEXT)')
    return connection


def decode_rates(path, rates):
    """{rate: mono float32 audio}: one libsndfile decode, resampled with soxr HQ to each rate (the app's stack)."""
    import soundfile
    import soxr
    audio, native = soundfile.read(str(path), dtype='float32', always_2d=True)
    audio = audio.mean(axis=1)
    return {rate: audio if rate == native else soxr.resample(audio, native, rate, quality='HQ').astype(np.float32)
            for rate in rates}


def below_normal_priority():
    try:
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 10)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app-data', default=str(REPO / 'dist'), help="folder with the app's library.sqlite")
    parser.add_argument('--models', nargs='+', default=DEFAULT_MODELS)
    parser.add_argument('--device', default='cuda', help='cuda or cpu')
    parser.add_argument('--decoders', type=int, default=3, help='parallel decoding threads')
    parser.add_argument('--threads', type=int, default=4, help='PyTorch CPU threads')
    args = parser.parse_args()

    # Always the research cache, even if HF_HOME is set globally (it is on the development machine).
    os.environ['HF_HOME'] = str(REPO / '.research_cache' / 'hf')
    os.environ['HF_HUB_OFFLINE'] = '1'
    import torch
    if args.device == 'cuda' and not torch.cuda.is_available():
        sys.exit('CUDA is not available in this environment; use --device cpu.')
    torch.set_num_threads(args.threads)
    below_normal_priority()

    library = copy_library(args.app_data)
    tracks = select_tracks(library)
    (OUT / 'tracks.json').write_text(json.dumps([key for key, _ in tracks]))
    print(f'{len(tracks)} tracks (rating 4-5, colour set, file present)', flush=True)

    stores = {key: open_store(key) for key in args.models}
    done = {key: {row[0] for row in store.execute('SELECT path_key FROM windows UNION SELECT path_key FROM errors')}
            for key, store in stores.items()}
    todo = [(path_key, path) for path_key, path in tracks if any(path_key not in done[m] for m in args.models)]
    for key in args.models:
        print(f'{key}: {len(done[key])} done', flush=True)
    print(f'{len(todo)} tracks to process on {args.device}', flush=True)
    if not todo:
        return

    models = {}
    for key in args.models:
        models[key] = load_model(key)
        models[key].audio_to(args.device)
    rates = sorted({model.rate for model in models.values()})

    started = time.perf_counter()
    with ThreadPoolExecutor(args.decoders) as pool:
        pending = deque()
        upcoming = iter(todo)

        def refill():
            while len(pending) < 2 * args.decoders:
                try:
                    path_key, path = next(upcoming)
                except StopIteration:
                    return
                pending.append((path_key, pool.submit(decode_rates, path, rates)))

        refill()
        number = 0
        while pending:
            path_key, future = pending.popleft()
            refill()
            number += 1
            try:
                audio = future.result()
            except Exception as error:  # an unreadable file must not stop a run of hours
                for key in args.models:
                    stores[key].execute('INSERT OR REPLACE INTO errors VALUES (?, ?)',
                                        (path_key, f'{type(error).__name__}: {error}'))
                    stores[key].commit()
                continue
            for key, model in models.items():
                if path_key in done[key]:
                    continue
                try:
                    windows = windows_of(audio[model.rate], model.window)
                    vectors = np.concatenate([model.embed_prepared(model.prepare(windows[i:i + BATCH]))
                                              for i in range(0, len(windows), BATCH)]).astype(np.float32)
                    stores[key].execute('INSERT OR REPLACE INTO windows VALUES (?, ?, ?, ?, ?)',
                                        (path_key, len(vectors), vectors.shape[1], model.window / model.rate,
                                         vectors.tobytes()))
                except Exception as error:
                    stores[key].execute('INSERT OR REPLACE INTO errors VALUES (?, ?)',
                                        (path_key, f'{type(error).__name__}: {error}'))
                stores[key].commit()
            if number % 25 == 0 or number == len(todo):
                elapsed = time.perf_counter() - started
                remaining = elapsed / number * (len(todo) - number)
                print(f'{number}/{len(todo)}: {elapsed / number:.2f} s per track (all models), '
                      f'about {remaining / 60:.0f} min left', flush=True)
    for store in stores.values():
        store.close()
    print('All done.', flush=True)


if __name__ == '__main__':
    main()

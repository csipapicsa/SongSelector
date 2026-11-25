"""Phase 1 data: a fixed, artist-aware split and a log-mel cache with the matching teacher vectors.

Split (written to a manifest, so every run uses the same tracks):
  test   the genre test set of ../clap/allmusiccaps.ipynb (rating 4-5 with a colour) that is in the teacher snapshot:
         the student is scored on it with the same 27 prompts as the teacher
  val    other tracks by the test set's artists: kept out of training (they would leak those artists into the test
         score) but artist-disjoint from training, so they serve early stopping and model choice
  train  the rest, no artist in common with val or test (tracks without an artist count as their own artist);
         `train_rank` is a seeded random order, so "the first N" gives nested subsets for a learning curve

Windows: up to 16 evenly spaced 10 s windows per training track (more examples per song), the 6 sampled windows for
val and test (as the app would on the CPU). Each window's target is the teacher vector at the same window index.

Each track is decoded with the app's decoder in a pool of processes; its windows go through the students' own LogMel
on the GPU, so the cached input is what the exported model computes (stored as float16). A track whose window
count differs from the snapshot (decoder changed since the app analysed it) is skipped and counted.

Output in .research_cache/distill/data/:
  manifest.parquet   one row per track: path_key, artist, genre, split, train_rank, frames, ok, first row, windows
  mel64.npy          (windows, 64, 1001) float16 log-mel
  teacher.npy        (windows, 512) float32 teacher vectors (as cached by the app, not normalised)
  windows.npz        per window: its track (manifest row) and window index in the track
  meta.json          front end, seed, counts, timing

    .research_cache\\venv-distill\\Scripts\\python research\\experiments\\distill\\prepare_data.py
"""
import argparse
import json
import random
import re
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from contextlib import closing
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    DATA,
    DIM,
    REPO,
    SAMPLED_WINDOWS,
    connect_ro,
    decode,
    library,
    sampled_indices,
    teacher_cache,
    teacher_vectors,
    windows_of,
)

CLAP_TEST = REPO / '.research_cache' / 'clap' / 'amc-all-layers.sqlite'   # the genre test set's track list
TRAIN_WINDOWS = 16
N_MELS = 64


def norm_artist(artist):
    return re.sub(r'\s+', ' ', (artist or '').strip().lower())


def build_manifest(seed):
    import pandas as pd
    with closing(connect_ro(teacher_cache())) as connection:
        frames = dict(connection.execute('SELECT path_key, frames FROM embeddings WHERE error IS NULL AND frames > 0'))
    with closing(connect_ro(CLAP_TEST)) as connection:
        test_keys = {key for (key,) in connection.execute('SELECT path_key FROM windows')} & frames.keys()
    with closing(connect_ro(library())) as connection:
        meta = {key: (artist or '', genre or '', file_path) for key, artist, genre, file_path in
                connection.execute('SELECT path_key, artist, genre, file_path FROM tracks')}
    test_artists = {norm_artist(meta[key][0]) for key in test_keys if key in meta} - {''}

    rows = []
    for key in sorted(frames):
        artist, genre, file_path = meta.get(key, ('', '', key))
        split = 'test' if key in test_keys else 'val' if norm_artist(artist) in test_artists else 'train'
        k = TRAIN_WINDOWS if split == 'train' else SAMPLED_WINDOWS
        rows.append({'path_key': key, 'file_path': file_path or key, 'artist': artist, 'genre': genre, 'split': split,
                     'frames': frames[key], 'indices': sampled_indices(frames[key], k).tolist()})
    manifest = pd.DataFrame(rows)
    train = manifest.index[manifest.split == 'train'].tolist()
    random.Random(seed).shuffle(train)
    manifest['train_rank'] = -1
    manifest.loc[train, 'train_rank'] = range(len(train))
    manifest['windows'] = manifest.indices.map(len)
    manifest['first'] = manifest.windows.cumsum() - manifest.windows
    return manifest


def load_windows(file_path, frames, indices):
    """Worker: decode one track, check its window count against the teacher cache, return the chosen windows."""
    try:
        windows = windows_of(decode(file_path))
    except Exception as error:   # unreadable file: counted, not fatal
        return 'error', f'{type(error).__name__}: {error}'
    if len(windows) != frames:
        return 'mismatch', f'{len(windows)} windows, the teacher cache has {frames}'
    return 'ok', np.ascontiguousarray(windows[indices])


def lower_priority():
    import psutil
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)   # the laptop stays usable


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--limit', type=int, help='only the first N tracks (a quick test)')
    args = parser.parse_args()

    import torch
    from students import LogMel

    manifest = build_manifest(args.seed)
    if args.limit:
        manifest = manifest.iloc[:args.limit].copy()
        manifest['first'] = manifest.windows.cumsum() - manifest.windows
    total = int(manifest.windows.sum())
    counts = manifest.split.value_counts().to_dict()
    print(f'{len(manifest)} tracks {counts}, {total} windows', flush=True)

    DATA.mkdir(parents=True, exist_ok=True)
    mel = np.lib.format.open_memmap(DATA / 'mel64.npy', mode='w+', dtype=np.float16, shape=(total, N_MELS, 1001))
    teacher = np.lib.format.open_memmap(DATA / 'teacher.npy', mode='w+', dtype=np.float32, shape=(total, DIM))
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    frontend = LogMel(N_MELS).to(device).eval()
    status, notes = ['pending'] * len(manifest), [''] * len(manifest)

    def store(row, result):
        state, value = result
        status[row], track = state, manifest.iloc[row]
        if state != 'ok':
            notes[row] = value
            return
        with torch.inference_mode():
            features = frontend(torch.from_numpy(value).to(device))
        first, count = int(track['first']), int(track['windows'])
        mel[first:first + count] = features.half().cpu().numpy()
        teacher[first:first + count] = teacher_vectors(track['path_key'])[track['indices']]

    started = time.time()
    with ProcessPoolExecutor(args.workers, initializer=lower_priority) as pool:
        pending, rows = {}, iter(range(len(manifest)))
        done = 0
        while True:
            while len(pending) < 2 * args.workers:   # a few tracks in flight: bounded memory
                row = next(rows, None)
                if row is None:
                    break
                track = manifest.iloc[row]
                pending[pool.submit(load_windows, track['file_path'], int(track['frames']), track['indices'])] = row
            if not pending:
                break
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                store(pending.pop(future), future.result())
                done += 1
                if done % 100 == 0 or done == len(manifest):
                    elapsed = time.time() - started
                    print(f'{done}/{len(manifest)} tracks, {elapsed / 60:.1f} min, '
                          f'ETA {elapsed / done * (len(manifest) - done) / 60:.1f} min', flush=True)
    mel.flush()
    teacher.flush()

    manifest['status'] = status
    manifest['ok'] = manifest.status == 'ok'
    manifest['note'] = notes
    manifest.to_parquet(DATA / 'manifest.parquet', index=False)
    track_of = np.repeat(np.arange(len(manifest)), manifest.windows)
    window_of = np.concatenate([np.asarray(i, dtype=np.int32) for i in manifest.indices])
    np.savez(DATA / 'windows.npz', track=track_of, window=window_of)
    meta = {
        'created': datetime.now().isoformat(timespec='seconds'), 'seed': args.seed, 'minutes': (time.time() - started) / 60,
        'tracks': len(manifest), 'windows': total, 'splits': counts,
        'ok_by_split': manifest[manifest.ok].split.value_counts().to_dict(),
        'skipped': manifest[~manifest.ok].status.value_counts().to_dict(),
        'train_windows_per_track': TRAIN_WINDOWS, 'eval_windows_per_track': SAMPLED_WINDOWS,
        'frontend': {'n_mels': N_MELS, 'n_fft': frontend.n_fft, 'hop': frontend.hop, 'rate': 24000, 'dtype': 'float16',
                     'computed_on': device},
    }
    (DATA / 'meta.json').write_text(json.dumps(meta, indent=1), encoding='utf-8')
    print(json.dumps(meta, indent=1))


if __name__ == '__main__':
    main()

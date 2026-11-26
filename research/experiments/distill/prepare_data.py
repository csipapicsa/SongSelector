"""Distillation data: a fixed, artist-disjoint split and a log-mel cache with the matching teacher vectors.

Split (written to a manifest, so every run uses the same tracks). No artist is in two of train, val and test
(artist names compared case-insensitively; a track without an artist counts as its own artist):
  test     the genre test set of ../clap/allmusiccaps.ipynb (rating 4-5 with a colour) that is in the teacher
           snapshot: the student is scored on it with the same 27 prompts as the teacher
  holdout  other tracks by the test set's artists: unused (in training or validation they would share artists with
           the test set)
  val      a seeded ~20 % of the remaining artists: early stopping and model choice
  train    the rest; `train_rank` is a seeded random order, so "the first N" gives nested subsets
Phase 1 used the holdout tracks as validation, which shared every artist with the test set; `--split-only` moved to
this split without rebuilding the cache (the Phase 1 manifest is kept as manifest-phase1.parquet).

Windows: up to 16 evenly spaced 10 s windows per train or val track (more examples per song; val comes from the same
pool, so a re-split needs no new windows), the 6 sampled windows for test and holdout (as the app would on the CPU).
Each window's target is the teacher vector at the same window index.

Each track is decoded with the app's decoder in a pool of processes; its windows go through the students' own LogMel
on the GPU, so the cached input is what the exported model computes (stored as float16). A track whose window
count differs from the snapshot (decoder changed since the app analysed it) is skipped and counted.

Output in .research_cache/distill/data/:
  manifest.parquet   one row per track: path_key, artist, genre, split, train_rank, frames, ok, first row, windows
  mel64.npy          (windows, 64, 1001) float16 log-mel
  mel128.npy         the same windows with 128 bands (--mels 128; 9 GB, for the 128-band students only)
  teacher.npy        (windows, 512) float32 teacher vectors (as cached by the app, not normalised)
  windows.npz        per window: its track (manifest row) and window index in the track
  meta.json          front end, seed, counts, timing

    .research_cache\\venv-distill\\Scripts\\python research\\experiments\\distill\\prepare_data.py
    .research_cache\\venv-distill\\Scripts\\python research\\experiments\\distill\\prepare_data.py --split-only
    .research_cache\\venv-distill\\Scripts\\python research\\experiments\\distill\\prepare_data.py --mels 128
"""
import argparse
import json
import random
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
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
VAL_SHARE = 0.2   # of the tracks that may be used for training, as whole artists


def norm_artist(artist):
    return re.sub(r'\s+', ' ', (artist or '').strip().lower())


def assign_splits(keys, artists, test_keys, seed):
    """{path_key: split} as described at the top. Fails if an artist ends up in two of train, val and test."""
    artist_of = {key: norm_artist(artist) or f'<no artist>:{key}' for key, artist in zip(keys, artists)}
    test_artists = {artist_of[key] for key in keys if key in test_keys}
    split = {key: 'test' if key in test_keys else 'holdout' if artist_of[key] in test_artists else None
             for key in keys}
    tracks_of = Counter(artist_of[key] for key in keys if split[key] is None)
    pool = sorted(tracks_of)
    random.Random(seed).shuffle(pool)
    val_artists, taken = set(), 0
    for artist in pool:
        if taken >= VAL_SHARE * sum(tracks_of.values()):
            break
        val_artists.add(artist)
        taken += tracks_of[artist]
    for key in keys:
        if split[key] is None:
            split[key] = 'val' if artist_of[key] in val_artists else 'train'

    splits_of = defaultdict(set)   # holdout counts as test here: it is the test artists' other tracks
    for key in keys:
        splits_of[artist_of[key]].add('test' if split[key] == 'holdout' else split[key])
    shared = [artist for artist, splits in splits_of.items() if len(splits) > 1]
    if shared:
        sys.exit(f'{len(shared)} artists are in more than one split, e.g. {shared[:3]}')
    return split


def windows_for(split):
    return TRAIN_WINDOWS if split in ('train', 'val') else SAMPLED_WINDOWS


def rank_training(manifest, seed):
    train = manifest.index[manifest.split == 'train'].tolist()
    random.Random(seed).shuffle(train)
    manifest['train_rank'] = -1
    manifest.loc[train, 'train_rank'] = range(len(train))


def build_manifest(seed):
    import pandas as pd
    with closing(connect_ro(teacher_cache())) as connection:
        frames = dict(connection.execute('SELECT path_key, frames FROM embeddings WHERE error IS NULL AND frames > 0'))
    with closing(connect_ro(CLAP_TEST)) as connection:
        test_keys = {key for (key,) in connection.execute('SELECT path_key FROM windows')} & frames.keys()
    with closing(connect_ro(library())) as connection:
        meta = {key: (artist or '', genre or '', file_path) for key, artist, genre, file_path in
                connection.execute('SELECT path_key, artist, genre, file_path FROM tracks')}

    keys = sorted(frames)
    split = assign_splits(keys, [meta.get(key, ('',))[0] for key in keys], test_keys, seed)
    rows = []
    for key in keys:
        artist, genre, file_path = meta.get(key, ('', '', key))
        rows.append({'path_key': key, 'file_path': file_path or key, 'artist': artist, 'genre': genre,
                     'split': split[key], 'frames': frames[key],
                     'indices': sampled_indices(frames[key], windows_for(split[key])).tolist()})
    manifest = pd.DataFrame(rows)
    rank_training(manifest, seed)
    manifest['windows'] = manifest.indices.map(len)
    manifest['first'] = manifest.windows.cumsum() - manifest.windows
    return manifest


def split_only(seed):
    """Re-split the existing cache: only the split column and the training order change, never the cached windows."""
    import pandas as pd
    manifest = pd.read_parquet(DATA / 'manifest.parquet')
    backup = DATA / 'manifest-phase1.parquet'
    if not backup.exists():
        shutil.copy2(DATA / 'manifest.parquet', backup)
        shutil.copy2(DATA / 'meta.json', DATA / 'meta-phase1.json')
    test_keys = set(manifest.path_key[manifest.split == 'test'])
    split = assign_splits(manifest.path_key.tolist(), manifest.artist.tolist(), test_keys, seed)
    manifest['split'] = manifest.path_key.map(split)
    expected = [sampled_indices(frames, windows_for(s)).tolist() for frames, s in zip(manifest.frames, manifest.split)]
    changed = sum(list(have) != want for have, want in zip(manifest.indices, expected))
    if changed:
        sys.exit(f'{changed} tracks would need other windows than the cache holds: rebuild with prepare_data.py')
    rank_training(manifest, seed)
    manifest.to_parquet(DATA / 'manifest.parquet', index=False)

    meta = json.loads((DATA / 'meta.json').read_text(encoding='utf-8'))
    meta['splits'] = manifest.split.value_counts().to_dict()
    meta['ok_by_split'] = manifest[manifest.ok].split.value_counts().to_dict()
    meta['resplit'] = {'at': datetime.now().isoformat(timespec='seconds'), 'seed': seed, 'val_share': VAL_SHARE,
                       'previous_manifest': backup.name}
    (DATA / 'meta.json').write_text(json.dumps(meta, indent=1), encoding='utf-8')
    ok = manifest[manifest.ok]
    for name, group in ok.groupby('split'):
        artists = group.artist.map(norm_artist)
        print(f'{name:8s} {len(group):5d} tracks, {group.windows.sum():6d} windows, '
              f'{artists[artists != ""].nunique():4d} named artists')


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


def decode_all(manifest, workers, store):
    """Decode every manifest track in a pool of processes; store(row, result) gets each one as it finishes."""
    started = time.time()
    with ProcessPoolExecutor(workers, initializer=lower_priority) as pool:
        pending, rows = {}, iter(range(len(manifest)))
        done = 0
        while True:
            while len(pending) < 2 * workers:   # a few tracks in flight: bounded memory
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
    return (time.time() - started) / 60


def mels_only(n_mels, workers):
    """Another log-mel resolution of the cached windows: mel<n_mels>.npy, row for row like mel64.npy (manifest,
    teacher vectors and split unchanged). Every track is decoded again; its windows also go through the 64-band front
    end and are compared with mel64.npy, so each row of the new cache is shown to be the same audio."""
    import pandas as pd
    import torch
    from students import LogMel
    manifest = pd.read_parquet(DATA / 'manifest.parquet')
    reference = np.load(DATA / f'mel{N_MELS}.npy', mmap_mode='r')
    path = DATA / f'mel{n_mels}.npy'
    mel = np.lib.format.open_memmap(path, mode='w+', dtype=np.float16,
                                    shape=(len(reference), n_mels, reference.shape[2]))
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    frontend, check = LogMel(n_mels).to(device).eval(), LogMel(N_MELS).to(device).eval()
    worst, failed = [0.0], []
    todo = manifest[manifest.ok].reset_index()   # 'index' = the manifest row, as in windows.npz

    def store(row, result):
        state, value = result
        track = todo.iloc[row]
        if state != 'ok':   # this track was cached before: the audio or the decoder changed since
            failed.append(f"{track['path_key']}: {value}")
            return
        first, count = int(track['first']), int(track['windows'])
        with torch.inference_mode():
            audio = torch.from_numpy(value).to(device)
            mel[first:first + count] = frontend(audio).half().cpu().numpy()
            again = check(audio).half().cpu().numpy().astype(np.float32)
        diff = float(np.abs(again - reference[first:first + count].astype(np.float32)).max())
        # float16 rounds log-mels near 10-20 in steps of 0.008-0.016; another window would differ by whole units
        if diff > 0.05:
            sys.exit(f"{track['path_key']}: {N_MELS}-band check failed, max difference {diff:.3f} from mel{N_MELS}.npy")
        worst[0] = max(worst[0], diff)

    minutes = decode_all(todo, workers, store)
    mel.flush()
    if failed:
        sys.exit(f'{len(failed)} cached tracks could not be decoded the same way again, e.g. {failed[:3]}')
    meta = json.loads((DATA / 'meta.json').read_text(encoding='utf-8'))
    meta.setdefault('extra_mel_caches', {})[str(n_mels)] = {
        'file': path.name, 'created': datetime.now().isoformat(timespec='seconds'), 'minutes': minutes,
        'tracks': len(todo), 'windows': len(reference), 'n_fft': frontend.n_fft, 'hop': frontend.hop,
        'computed_on': device, f'max_diff_vs_mel{N_MELS}': worst[0]}
    (DATA / 'meta.json').write_text(json.dumps(meta, indent=1), encoding='utf-8')
    print(json.dumps(meta['extra_mel_caches'][str(n_mels)], indent=1))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--limit', type=int, help='only the first N tracks (a quick test)')
    parser.add_argument('--split-only', action='store_true',
                        help='re-split the existing cache (manifest only, no decoding); keeps the old manifest')
    parser.add_argument('--mels', type=int, metavar='N',
                        help='add mel<N>.npy for the cached windows (e.g. 128); nothing else changes')
    args = parser.parse_args()
    if args.split_only:
        split_only(args.seed)
        return
    if args.mels:
        mels_only(args.mels, args.workers)
        return

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

    minutes = decode_all(manifest, args.workers, store)
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
        'created': datetime.now().isoformat(timespec='seconds'), 'seed': args.seed, 'minutes': minutes,
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

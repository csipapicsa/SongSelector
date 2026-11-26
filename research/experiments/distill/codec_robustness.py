"""Codec robustness: does a track give the same vectors, and the same neighbours, as a low-bitrate MP3 copy?

Free training sets are often low-bitrate MP3s. In distillation the teacher labels whatever audio the student gets, so
a bad copy never gets a wrong label; the questions are whether the teacher itself drifts on such audio (then
low-quality data is a problem for the method, not only for the student) and whether the student drifts more.

For --tracks test tracks (seeded sample of the test split):
  1. the original file is re-encoded to MP3 at --kbps (libmp3lame CBR through PyAV, the FFmpeg the app ships;
     source sample rate and channels kept, like a low-quality download), into --out-dir;
  2. both are decoded with the app's decoder; the copy must have the same length and no time shift (checked: the
     decoder removes the encoder delay), so the 6 sampled windows hold the same moments;
  3. the teacher (CPU) and each student embed both versions' windows.
Measured per model: window and track cosine between original and copy; top-10 stability (neighbours among the 1,272
test tracks, the query's own original and its exact duplicates excluded, for the original vs the copy as query);
whether the copy finds its own original (or a duplicate of it) first; the cosine to the 10th neighbour as the scale a
drift has to stay under. Per student also the
fidelity to the teacher on each version. Per mel band: how much the copy's log-mel differs (where the codec acts).

One MLflow run in experiment distill-robustness, and a JSON in research/results/ (manifest rows, no track names).

    python codec_robustness.py --out-dir D:/SongSelector-research/codec \
        --students cnn4-small-64-n1199-cosine cnn4-small-64-tcn-n1199-cosine
"""
import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, RATE, RESULTS, TEACHER_ONNX, WORK, decode, mlflow_experiment, windows_of  # noqa: E402
from evaluate import load_split, student_test_tracks, track_vectors  # noqa: E402

EXPERIMENT = 'distill-robustness'
MAX_LAG = RATE // 10   # look for a time shift of up to 0.1 s
MP3_RATES = {8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000}


def unit(x):
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-9)


# ---- Re-encoding ---------------------------------------------------------------------------------------------------

def encode(source, target, kbps):
    """Worker: source -> MP3 at kbps (CBR), same sample rate and channels. Returns facts about the source."""
    import av
    with av.open(str(source)) as inp:
        stream = inp.streams.audio[0]
        info = {'codec': stream.codec_context.name, 'rate': stream.rate, 'channels': stream.channels,
                'kbps': round((inp.bit_rate or 0) / 1000)}
        if Path(target).exists():
            return info
        partial = Path(target).with_suffix('.partial.mp3')
        # LAME takes only MPEG sample rates and a named mono/stereo layout (a WAV may say just "2 channels")
        rate = stream.rate if stream.rate in MP3_RATES else 44100
        layout = 'stereo' if stream.channels >= 2 else 'mono'
        with av.open(str(partial), 'w') as out:
            mp3 = out.add_stream('libmp3lame', rate=rate, layout=layout)
            mp3.bit_rate = kbps * 1000
            resampler = av.AudioResampler(format=mp3.codec_context.format.name, layout=layout, rate=rate,
                                          frame_size=mp3.codec_context.frame_size or 1152)
            for packet in inp.demux(stream):
                try:
                    frames = packet.decode()
                except av.error.InvalidDataError:   # a damaged frame: skipped (the copy gets shorter; the length
                    info['damaged_frames'] = info.get('damaged_frames', 0) + 1   # check then leaves it out)
                    continue
                for frame in frames:
                    frame.pts = None
                    for chunk in resampler.resample(frame):
                        out.mux(mp3.encode(chunk))
            for chunk in resampler.resample(None):
                out.mux(mp3.encode(chunk))
            out.mux(mp3.encode(None))
    partial.replace(target)
    return info


def lower_priority():
    import psutil
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)


def lag_of(original, copy):
    """Time shift of the copy in samples (0 = aligned), from 5 s in the middle of the track."""
    mid = len(original) // 2
    segment = original[mid:mid + 5 * RATE]
    if len(segment) < RATE or mid < MAX_LAG:
        return 0
    span = copy[mid - MAX_LAG:mid + MAX_LAG + len(segment)]
    corr = np.correlate(span, segment, mode='valid')
    return int(np.argmax(corr)) - MAX_LAG


# ---- Models --------------------------------------------------------------------------------------------------------

def load_students(run_names):
    import torch
    from students import STUDENTS
    models = {}
    for name in run_names:
        model = STUDENTS[name.rsplit('-n', 1)[0]]()
        model.load_state_dict(torch.load(WORK / 'trained' / name / 'state_dict.pt', weights_only=True))
        models[name] = model.eval()
    return models


def embed_student(model, windows):
    import torch
    with torch.inference_mode():
        return model(torch.from_numpy(np.ascontiguousarray(windows))).numpy()


# ---- Metrics -------------------------------------------------------------------------------------------------------

def duplicate_groups(teacher_pool, pool_ids):
    """{track: its own id and those of exact duplicates}: the library has songs in two folders (2026-11-25), and a
    copy that finds its original's duplicate has found itself; duplicates are no one's neighbours either."""
    same = teacher_pool @ teacher_pool.T > 0.9999
    return {int(track): set(pool_ids[same[i]].tolist()) for i, track in enumerate(pool_ids)}


def neighbours(query, pool, pool_ids, exclude, k=10):
    sims = pool @ query
    sims[np.isin(pool_ids, list(exclude))] = -np.inf
    return set(pool_ids[np.argpartition(-sims, k)[:k]])


def model_metrics(orig_windows, copy_windows, orig_tracks, copy_tracks, query_ids, pool, pool_ids, itself):
    window_cos = (unit(orig_windows) * unit(copy_windows)).sum(1)
    track_cos = (orig_tracks * copy_tracks).sum(1)
    stable, first, nn10 = [], [], []
    for i, track in enumerate(query_ids):
        own = itself[int(track)]
        a = neighbours(orig_tracks[i], pool, pool_ids, own)
        b = neighbours(copy_tracks[i], pool, pool_ids, own)
        stable.append(len(a & b) / 10)
        first.append(int(pool_ids[np.argmax(pool @ copy_tracks[i])]) in own)
        others = np.sort(pool[~np.isin(pool_ids, list(own))] @ orig_tracks[i])[::-1]
        nn10.append(others[9])
    return {'window_cos_mean': float(window_cos.mean()), 'window_cos_p5': float(np.percentile(window_cos, 5)),
            'window_cos_min': float(window_cos.min()), 'track_cos_mean': float(track_cos.mean()),
            'track_cos_min': float(track_cos.min()), 'top10_stable': float(np.mean(stable)),
            'self_first': float(np.mean(first)), 'nn10_cos_median': float(np.median(nn10))}, track_cos, stable


def band_centres(n_mels=64, fmin=30.0, fmax=11000.0):
    def to_mel(hz):
        return 2595.0 * np.log10(1.0 + np.asarray(hz) / 700.0)
    mels = np.linspace(to_mel(fmin), to_mel(fmax), n_mels + 2)[1:-1]
    return 700.0 * (10.0 ** (mels / 2595.0) - 1.0)


# ---- Main ----------------------------------------------------------------------------------------------------------

def main():
    import pandas as pd
    import torch
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--tracks', type=int, default=100)
    parser.add_argument('--kbps', type=int, default=64)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--students', nargs='+', default=['cnn4-small-64-n1199-cosine'], metavar='RUN')
    parser.add_argument('--out-dir', type=Path, default=WORK / 'codec', help='where the MP3 copies go')
    parser.add_argument('--workers', type=int, default=4, help='parallel encoders')
    parser.add_argument('--threads', type=int, default=4, help='CPU threads for the teacher and the students')
    parser.add_argument('--out', type=Path, default=RESULTS / f'{date.today()}_distill_codec_robustness.json')
    args = parser.parse_args()
    torch.set_num_threads(args.threads)

    manifest = pd.read_parquet(DATA / 'manifest.parquet')
    test = manifest[(manifest.split == 'test') & manifest.ok]
    sample = test.sample(args.tracks, random_state=args.seed).sort_index()
    target_dir = args.out_dir / f'{args.kbps}k'
    target_dir.mkdir(parents=True, exist_ok=True)
    targets = {row: target_dir / f'{row}.mp3' for row in sample.index}   # manifest row, no names on disk

    started = time.time()
    with ProcessPoolExecutor(args.workers, initializer=lower_priority) as pool:
        futures = {row: pool.submit(encode, sample.file_path[row], targets[row], args.kbps) for row in sample.index}
        sources = {row: future.result() for row, future in futures.items()}
    encode_minutes = (time.time() - started) / 60
    print(f'{len(sources)} copies at {args.kbps} kbps in {encode_minutes:.1f} min', flush=True)

    from benchmark_speed import session
    from students import LogMel
    teacher = session(TEACHER_ONNX, args.threads)
    teacher_input = teacher.get_inputs()[0].name
    students = load_students(args.students)
    frontend = LogMel(64).eval()
    labels = ['teacher', *args.students]
    vectors = {label: {'orig': [], 'copy': []} for label in labels}
    window_track, lags, skipped, band_diff, band_abs = [], {}, {}, [], []
    started = time.time()
    for done, (row, track) in enumerate(sample.iterrows(), 1):
        original, copy = decode(track.file_path), decode(str(targets[row]))
        if len(original) != len(copy):
            skipped[row] = f'length {len(copy)} vs {len(original)}'
            continue
        lags[row] = lag_of(original, copy)
        index = np.asarray(track.indices)
        versions = {'orig': windows_of(original)[index], 'copy': windows_of(copy)[index]}
        for version, windows in versions.items():
            vectors['teacher'][version].append(teacher.run(None, {teacher_input: windows})[0])
            for name, model in students.items():
                vectors[name][version].append(embed_student(model, windows))
        with torch.inference_mode():
            mel_orig = frontend(torch.from_numpy(versions['orig'])).numpy()
            mel_copy = frontend(torch.from_numpy(versions['copy'])).numpy()
        band_diff.append((mel_copy - mel_orig).mean(2))          # (windows, bands), in natural-log power units
        band_abs.append(np.abs(mel_copy - mel_orig).mean(2))
        window_track += [row] * len(index)
        if done % 20 == 0:
            print(f'{done}/{len(sample)} tracks embedded, {(time.time() - started) / 60:.1f} min', flush=True)
    window_track = np.asarray(window_track)

    # Pools: the test split's track vectors from the caches (teacher: the app's vectors; students: cached log-mels)
    rows, test_track_ids, _ = load_split('test')
    teacher_pool, pool_ids = track_vectors(np.asarray(np.load(DATA / 'teacher.npy', mmap_mode='r')[rows]),
                                           test_track_ids)
    pools = {'teacher': teacher_pool}
    for name in args.students:
        pools[name], ids = student_test_tracks(name)
        assert (ids == pool_ids).all()
    itself = duplicate_groups(teacher_pool, pool_ids)

    summary, per_track = {}, {}
    for label in labels:
        orig = np.concatenate(vectors[label]['orig'])
        copy = np.concatenate(vectors[label]['copy'])
        orig_tracks, query_ids = track_vectors(orig, window_track)
        copy_tracks, _ = track_vectors(copy, window_track)
        per_track.setdefault('row', [int(row) for row in query_ids])
        metrics, track_cos, stable = model_metrics(orig, copy, orig_tracks, copy_tracks, query_ids, pools[label],
                                                   pool_ids, itself)
        # The fresh original vectors must match the pool's own vectors of the same tracks (same windows, same model)
        pool_rows = np.searchsorted(pool_ids, query_ids) if (np.diff(pool_ids) > 0).all() else \
            np.array([int(np.flatnonzero(pool_ids == t)[0]) for t in query_ids])
        metrics['fresh_vs_pool_cos_min'] = float((orig_tracks * pools[label][pool_rows]).sum(1).min())
        if label != 'teacher':
            teacher_orig = np.concatenate(vectors['teacher']['orig'])
            teacher_copy = np.concatenate(vectors['teacher']['copy'])
            metrics['fidelity_orig'] = float((unit(orig) * unit(teacher_orig)).sum(1).mean())
            metrics['fidelity_copy'] = float((unit(copy) * unit(teacher_copy)).sum(1).mean())
        summary[label] = metrics
        per_track[f'{label}/track_cos'] = np.round(track_cos, 5).tolist()
        per_track[f'{label}/top10_stable'] = stable
        print(f'{label}: ' + ', '.join(f'{key} {value:.4f}' for key, value in metrics.items()), flush=True)

    centres = band_centres()
    bands = pd.DataFrame({'band': range(64), 'centre_hz': np.round(centres),
                          'mean_diff': np.concatenate(band_diff).mean(0).round(4),
                          'mean_abs_diff': np.concatenate(band_abs).mean(0).round(4)})
    per_track = pd.DataFrame(per_track)
    per_track['ext'] = [sample.file_path[r].rsplit('.', 1)[-1].lower() for r in per_track.row]
    per_track['source_kbps'] = [sources[r]['kbps'] for r in per_track.row]
    per_track['lag_samples'] = [lags[r] for r in per_track.row]
    source_mix = Counter(f"{info['codec']}" for info in sources.values())

    out = {
        'date': str(date.today()),
        'question': f'Codec robustness: original vs a {args.kbps} kbps MP3 copy of {len(per_track)} test tracks. '
                    'Does the teacher drift (then low-quality data is a problem for distillation itself), and does '
                    'the student drift more?',
        'setup': {'tracks': len(per_track), 'kbps': args.kbps, 'seed': args.seed, 'encoder': 'libmp3lame CBR, PyAV',
                  'sources': dict(source_mix), 'source_kbps_median': float(per_track.source_kbps.median()),
                  'max_abs_lag_samples': int(per_track.lag_samples.abs().max()), 'skipped': {str(row): why for row, why in skipped.items()},
                  'sources_with_damaged_frames': sum('damaged_frames' in info for info in sources.values()),
                  'queries_with_exact_duplicates': sum(len(itself[row]) > 1 for row in per_track.row),
                  'pool': f'{len(pool_ids)} test tracks', 'windows_per_track': 6, 'encode_minutes': encode_minutes},
        'models': summary,
        'mel_bands': {'mean_abs_diff_all': float(bands.mean_abs_diff.mean()),
                      'mean_abs_diff_below_4k': float(bands.mean_abs_diff[bands.centre_hz < 4000].mean()),
                      'mean_abs_diff_above_8k': float(bands.mean_abs_diff[bands.centre_hz > 8000].mean()),
                      'per_band': bands.to_dict('records')},
        'per_track': per_track.to_dict('records'),
    }
    args.out.write_text(json.dumps(out, indent=1), encoding='utf-8')
    print(f'Wrote {args.out}')

    mlflow = mlflow_experiment(EXPERIMENT)
    with mlflow.start_run(run_name=f'codec-{args.kbps}k-n{len(per_track)}'):
        mlflow.log_params({'tracks': len(per_track), 'kbps': args.kbps, 'seed': args.seed,
                           'encoder': 'libmp3lame CBR (PyAV)', 'students': ','.join(args.students),
                           'sources': ', '.join(f'{k}: {v}' for k, v in source_mix.items()),
                           'source_kbps_median': out['setup']['source_kbps_median'], 'skipped': len(skipped)})
        for label, metrics in summary.items():
            mlflow.log_metrics({f'{label}/{key}': value for key, value in metrics.items()})
        mlflow.log_metrics({f'mel/{key}': value for key, value in out['mel_bands'].items() if key != 'per_band'})
        mlflow.log_metric('max_abs_lag_samples', out['setup']['max_abs_lag_samples'])
        mlflow.log_table(bands, 'mel_band_diff.json')
        mlflow.log_table(per_track, 'per_track.json')
        mlflow.log_artifact(str(args.out))


if __name__ == '__main__':
    main()

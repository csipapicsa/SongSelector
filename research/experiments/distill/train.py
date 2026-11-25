"""Train a student to predict the teacher's window vectors from cached log-mels; one MLflow run each.

    python train.py --student cnn4-64                    # all training tracks
    python train.py --student cnn4-64 --train-tracks 500 # learning curve
    python train.py --student mean                       # baseline: the mean training vector for every window
    python train.py --student ridge-mfcc40               # baseline: MFCC mean/std -> ridge regression
    python train.py --student cnn4-small-64 --train-tracks 50 --max-epochs 300 --patience 300 --eval-train
                                                         # can it fit a few tracks at all? (overfitting test)

Loss: 1 - cosine(student, teacher) per window. Only directions count: the teacher vectors are not unit length,
and the app compares directions. AdamW with a fixed learning rate, fp32 on the GPU, early stopping on
the validation window cosine (at most --max-epochs, stop after --patience epochs without a better one), and the
best epoch's weights are kept. No augmentation: the targets belong to the unchanged audio.

Logged per run (experiment distill-train): settings, train loss and validation cosine per epoch (with --eval-train
also the cosine on up to 4,096 training windows in eval mode, comparable with the validation cosine; the train loss
is measured in training mode, while the weights change), then for the best
weights val/test fidelity (evaluate.fidelity) and test genre AP, the ONNX export (front end included, checked
against PyTorch) and the state dict.
"""
import argparse
import hashlib
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, WORK, mlflow_experiment  # noqa: E402
from evaluate import EXPERIMENT, fidelity, genre_ap, genres_of, text_vectors, track_vectors  # noqa: E402

BASELINES = ['mean', 'ridge-mfcc40']


def unit(x):
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-9)


def load_data(train_tracks, seed):
    import pandas as pd
    manifest = pd.read_parquet(DATA / 'manifest.parquet')
    track = np.load(DATA / 'windows.npz')['track']
    mel = np.load(DATA / 'mel64.npy', mmap_mode='r')
    teacher = np.load(DATA / 'teacher.npy', mmap_mode='r')
    ok = manifest.ok.to_numpy()
    train_ids = manifest.index[ok & (manifest.split == 'train').to_numpy()
                               & (manifest.train_rank < (train_tracks or 10**9)).to_numpy()]
    data = {'manifest': manifest, 'mel': mel, 'teacher': teacher, 'train_track_count': len(train_ids)}
    for split, ids in (('train', train_ids),
                       ('val', manifest.index[ok & (manifest.split == 'val').to_numpy()]),
                       ('test', manifest.index[ok & (manifest.split == 'test').to_numpy()])):
        rows = np.flatnonzero(np.isin(track, ids))
        data[split] = {'rows': rows, 'tracks': track[rows], 'teacher': np.asarray(teacher[rows], dtype=np.float32)}
    data['manifest_sha'] = hashlib.sha256((DATA / 'manifest.parquet').read_bytes()).hexdigest()[:12]
    return data


def mel_of(data, split):
    """The split's log-mels in memory (float16; the training split is a few GB)."""
    return np.asarray(data['mel'][data[split]['rows']])


# ---- Baselines -----------------------------------------------------------------------------------------------------

def mfcc_stats(mel, n_mfcc=40, chunk=2048):
    from students import dct_matrix
    dct = dct_matrix(mel.shape[1], n_mfcc)
    out = []
    for start in range(0, len(mel), chunk):
        mfcc = np.matmul(mel[start:start + chunk].astype(np.float32).transpose(0, 2, 1), dct)
        out.append(np.concatenate([mfcc.mean(1), mfcc.std(1)], axis=1))
    return np.concatenate(out)


def fit_baseline(name, data, log):
    """Predictions for val and test from a baseline that needs no network."""
    target = unit(data['train']['teacher'])
    if name == 'mean':
        mean = unit(target.mean(0))
        return {split: np.tile(mean, (len(data[split]['rows']), 1)) for split in ('val', 'test')}
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    features = {split: mfcc_stats(mel_of(data, split)) for split in ('train', 'val', 'test')}
    scaler = StandardScaler().fit(features['train'])
    features = {split: scaler.transform(value) for split, value in features.items()}
    best = None
    for alpha in (0.1, 1, 10, 100, 1000):      # chosen on validation, never on test
        model = Ridge(alpha=alpha).fit(features['train'], target)
        cos = (unit(model.predict(features['val'])) * unit(data['val']['teacher'])).sum(1).mean()
        log(f'ridge alpha {alpha}: val cosine {cos:.4f}')
        if best is None or cos > best[0]:
            best = (cos, alpha, model)
    return {'alpha': best[1], **{split: best[2].predict(features[split]) for split in ('val', 'test')}}


# ---- Students ------------------------------------------------------------------------------------------------------

def predict(model, mel, device, amp=False, batch=128):
    import torch
    model.eval()
    out = []
    with torch.inference_mode(), torch.autocast(device, dtype=torch.float16, enabled=amp):
        for start in range(0, len(mel), batch):
            x = torch.from_numpy(mel[start:start + batch]).to(device).float()
            out.append(model.embed_mel(x).float().cpu().numpy())
    return np.concatenate(out)


def train_student(name, data, args, mlflow, log):
    import torch
    import torch.nn.functional as F
    from students import STUDENTS
    torch.manual_seed(args.seed)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = STUDENTS[name]().to(device)
    if model.n_mels != data['mel'].shape[1]:
        sys.exit(f'{name} needs {model.n_mels} mel bands; the cache has {data["mel"].shape[1]}')
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = None
    if args.schedule == 'cosine':   # from --lr down to 0 over all --max-epochs, a step per batch
        steps = args.max_epochs * (len(data['train']['rows']) // args.batch)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=steps)
    # Off by default: on the GTX 1650 Ti fp16 gives NaN from the first step (and is slower than fp32 there).
    amp = args.amp and device == 'cuda'
    scaler = torch.amp.GradScaler(enabled=amp)

    train_mel, val_mel = mel_of(data, 'train'), mel_of(data, 'val')
    train_unit = unit(data['train']['teacher'])
    train_target = torch.from_numpy(train_unit).to(device)
    val_target = unit(data['val']['teacher'])
    rng = np.random.default_rng(args.seed)
    check_rows = None
    if args.eval_train:   # a fixed sample, drawn apart from the training order
        check_rows = np.sort(np.random.default_rng(args.seed + 1).choice(
            len(train_mel), min(4096, len(train_mel)), replace=False))
    best = {'cos': -1.0, 'epoch': 0, 'state': None}
    for epoch in range(1, args.max_epochs + 1):
        model.train()
        started, losses = time.time(), []
        order = rng.permutation(len(train_mel))
        for start in range(0, len(order) - args.batch + 1, args.batch):   # drop the last partial batch (BatchNorm)
            index = np.sort(order[start:start + args.batch])
            x = torch.from_numpy(train_mel[index]).to(device, non_blocking=True).float()
            with torch.autocast(device, dtype=torch.float16, enabled=amp):
                prediction = model.embed_mel(x)
            target = train_target[torch.from_numpy(index).to(device)]
            loss = (1 - F.cosine_similarity(prediction.float(), target, dim=-1)).mean()
            optimizer.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            if scheduler is not None:
                scheduler.step()
            losses.append(loss.item())
        val_cos = float((unit(predict(model, val_mel, device, amp)) * val_target).sum(1).mean())
        if not np.isfinite(val_cos):
            sys.exit(f'epoch {epoch}: validation cosine is {val_cos} (NaN in training?)')
        metrics = {'train_loss': float(np.mean(losses)), 'val_cos': val_cos, 'epoch_s': time.time() - started,
                   'lr': optimizer.param_groups[0]['lr']}
        if check_rows is not None:
            metrics['train_cos'] = float((unit(predict(model, train_mel[check_rows], device, amp))
                                          * train_unit[check_rows]).sum(1).mean())
        mlflow.log_metrics(metrics, step=epoch)
        improved = val_cos > best['cos']
        log(f'epoch {epoch:2d}: train loss {np.mean(losses):.4f}, '
            + (f'train cosine {metrics["train_cos"]:.4f}, ' if check_rows is not None else '')
            + f'val cosine {val_cos:.4f}{" (best)" if improved else ""}, {time.time() - started:.0f} s')
        if improved:
            best = {'cos': val_cos, 'epoch': epoch,
                    'state': {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}}
        elif epoch - best['epoch'] >= args.patience:
            log(f'early stop: no better validation cosine for {args.patience} epochs')
            break
    if device == 'cuda':
        peak = torch.cuda.max_memory_allocated() / 1e6
        mlflow.log_metric('gpu_peak_mb', peak)
        log(f'peak GPU memory {peak:.0f} MB')
    model.load_state_dict(best['state'])
    predictions = {'val': predict(model, val_mel, device, amp), 'test': predict(model, mel_of(data, 'test'), device, amp)}
    return model.cpu(), best, predictions


# ---- Main ----------------------------------------------------------------------------------------------------------

def main():
    from students import STUDENTS
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--student', required=True, choices=BASELINES + list(STUDENTS))
    parser.add_argument('--train-tracks', type=int, help='the first N training tracks (default: all)')
    parser.add_argument('--lr', type=float, default=3e-4)
    parser.add_argument('--schedule', choices=['constant', 'cosine'], default='constant',
                        help='cosine: the learning rate falls from --lr to 0 over --max-epochs')
    parser.add_argument('--weight-decay', type=float, default=1e-4)
    parser.add_argument('--batch', type=int, default=32)
    parser.add_argument('--max-epochs', type=int, default=10)
    parser.add_argument('--patience', type=int, default=3)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--amp', action='store_true', help='fp16 mixed precision (NaN on a GTX 1650 Ti)')
    parser.add_argument('--experiment', default=EXPERIMENT, help='MLflow experiment (e.g. distill-smoke for tests)')
    parser.add_argument('--eval-train', action='store_true', help='per epoch: cosine on training windows, eval mode')
    parser.add_argument('--phase', default='2', help='MLflow tag')
    parser.add_argument('--name-suffix', default='', help="added to the run name, e.g. 'overfit'")
    args = parser.parse_args()

    def log(message):
        print(message, flush=True)

    data = load_data(args.train_tracks, args.seed)
    mlflow = mlflow_experiment(args.experiment)
    kind = 'baseline' if args.student in BASELINES else 'student'
    name = f"{args.student}-n{data['train_track_count']}" + (f'-{args.name_suffix}' if args.name_suffix else '')
    with mlflow.start_run(run_name=name, tags={'phase': args.phase, 'kind': kind}):
        mlflow.log_params({'student': args.student, 'train_tracks': data['train_track_count'],
                           'train_windows': len(data['train']['rows']), 'val_windows': len(data['val']['rows']),
                           'test_windows': len(data['test']['rows']), 'manifest_sha': data['manifest_sha'],
                           'seed': args.seed})
        started = time.time()
        if kind == 'baseline':
            predictions = fit_baseline(args.student, data, log)
            if 'alpha' in predictions:
                mlflow.log_param('ridge_alpha', predictions['alpha'])
        else:
            mlflow.log_params({'lr': args.lr, 'weight_decay': args.weight_decay, 'batch': args.batch,
                               'max_epochs': args.max_epochs, 'patience': args.patience, 'optimizer': 'AdamW',
                               'schedule': args.schedule,
                               'loss': '1 - cosine', 'amp': args.amp, 'eval_train': args.eval_train})
            model, best, predictions = train_student(args.student, data, args, mlflow, log)
            mlflow.log_metrics({'best_epoch': best['epoch'], 'best_val_cos': best['cos'],
                                'params_m': sum(p.numel() for p in model.parameters()) / 1e6})
        mlflow.log_metric('train_minutes', (time.time() - started) / 60)

        metrics = {}
        for split in ('val', 'test'):
            for key, value in fidelity(predictions[split], data[split]['teacher'], data[split]['tracks']).items():
                metrics[f'{split}_{key}'] = value
        tracks, _ = track_vectors(predictions['test'], data['test']['tracks'])
        metrics['test_genre_ap'], per_prompt = genre_ap(tracks, genres_of(data['test']['tracks'], data['manifest']),
                                                        text_vectors())
        mlflow.log_metrics(metrics)
        import pandas as pd
        mlflow.log_table(pd.DataFrame(per_prompt), 'genre_ap_test.json')

        if kind == 'student':
            import torch
            from students import export
            out = WORK / 'trained' / name
            out.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), out / 'state_dict.pt')
            check = export(model, out / f'{name}.onnx')
            mlflow.log_metrics({'onnx_max_abs_diff': check['max_abs_diff'], 'onnx_min_cosine': check['min_cosine']})
            mlflow.log_artifacts(str(out), 'model')
        log(f"{name}: " + ', '.join(f'{key} {value:.4f}' for key, value in metrics.items()))


if __name__ == '__main__':
    main()

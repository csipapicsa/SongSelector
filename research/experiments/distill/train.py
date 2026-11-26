"""Train a student to predict the teacher's window vectors from cached log-mels; one MLflow run each.

    python train.py --student cnn4-64                    # all training tracks
    python train.py --student cnn4-64 --train-tracks 500 # learning curve
    python train.py --student mean                       # baseline: the mean training vector for every window
    python train.py --student ridge-mfcc40               # baseline: MFCC mean/std -> ridge regression
    python train.py --student cnn4-small-64 --train-tracks 50 --max-epochs 300 --patience 300 --eval-train
                                                         # can it fit a few tracks at all? (overfitting test)

    python train.py --student cnn4-small-64-tcn --max-epochs 40 --patience 40 --schedule cosine --eval-train \\
        --loss cosine+neighbours --select val_top10      # relational distillation, epoch chosen on neighbours

Loss: 1 - cosine(student, teacher) per window. Only directions count: the teacher vectors are not unit length,
and the app compares directions. --loss adds a relational part (make_loss): how each window relates to the
training tracks (neighbours) or to the other windows of the batch. AdamW, fp32 on the GPU, early stopping
(at most --max-epochs, stop after --patience epochs without a better one), and the best epoch's weights are kept:
best by validation cosine or, with --select val_top10, by validation top-10 neighbour overlap. No augmentation: the
targets belong to the unchanged audio.

Logged per run (experiment distill-train): settings, per epoch the train loss (and its parts), the validation
cosine and the validation top-10 neighbour overlap (with --eval-train also the cosine on up to 4,096 training windows
in eval mode, comparable with the validation cosine; the train loss is measured in training mode, while the weights
change), then for the chosen weights val/test fidelity (evaluate.fidelity) and test genre AP, the ONNX export (front
end included, checked against PyTorch) and the state dict; for the other selection rule its epoch and test top-10
overlap and window cosine (if_<rule>_*), so the loss and the selection rule can be told apart.
"""
import argparse
import hashlib
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, WORK, log_code_state, mlflow_experiment  # noqa: E402
from evaluate import (  # noqa: E402
    EXPERIMENT,
    fidelity,
    genre_ap,
    genres_of,
    text_vectors,
    top_k_overlap,
    track_vectors,
)

BASELINES = ['mean', 'ridge-mfcc40']
LOSSES = ['cosine', 'cosine+neighbours', 'cosine+batch-relations']
SELECT_RULES = ('val_cos', 'val_top10')


def unit(x):
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-9)


def mel_cache(n_mels):
    """The log-mel cache for n_mels bands: the same windows, row for row, in every resolution."""
    path = DATA / f'mel{n_mels}.npy'
    if not path.exists():
        sys.exit(f'{path.name} is missing: build it with prepare_data.py --mels {n_mels}')
    return np.load(path, mmap_mode='r')


def load_data(train_tracks, seed, n_mels=64, all_windows=False):
    """all_windows: the training tracks' other windows too (prepare_data.py --extra-train-windows), appended after
    the cached ones; validation and test are unchanged."""
    import pandas as pd
    manifest = pd.read_parquet(DATA / 'manifest.parquet')
    track = np.load(DATA / 'windows.npz')['track']
    mel = mel_cache(n_mels)
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
    if all_windows:
        if n_mels != 64 or not (DATA / 'train-extra.npz').exists():
            sys.exit('--all-windows needs the 64-band extra cache: prepare_data.py --extra-train-windows')
        extra_track = np.load(DATA / 'train-extra.npz')['track']
        extra_rows = np.flatnonzero(np.isin(extra_track, train_ids))
        extra_teacher = np.load(DATA / 'teacher-train-extra.npy', mmap_mode='r')
        data['extra_mel'] = np.load(DATA / 'mel64-train-extra.npy', mmap_mode='r')
        train = data['train']
        train['extra_rows'] = extra_rows
        train['tracks'] = np.concatenate([train['tracks'], extra_track[extra_rows]])
        train['teacher'] = np.concatenate([train['teacher'], np.asarray(extra_teacher[extra_rows], dtype=np.float32)])
    data['manifest_sha'] = hashlib.sha256((DATA / 'manifest.parquet').read_bytes()).hexdigest()[:12]
    return data


def mel_of(data, split):
    """The split's log-mels in memory (float16; the training split is a few GB, ~6 GB with --all-windows)."""
    rows, extra = data[split]['rows'], data[split].get('extra_rows')
    if extra is None:
        return np.asarray(data['mel'][rows])
    out = np.empty((len(rows) + len(extra),) + data['mel'].shape[1:], dtype=data['mel'].dtype)
    out[:len(rows)] = data['mel'][rows]
    out[len(rows):] = data['extra_mel'][extra]
    return out


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


def make_loss(kind, data, device, weight=1.0, tau=0.05):
    """loss(prediction, target, index) -> (total, {part: value}) for a batch of training windows (index: their rows
    in the training split).

    Every loss has the window term, 1 - cosine(student, teacher). The relational parts compare directions after
    removing the teacher's mean unit window vector, the direction every vector shares (it has length 0.67 here, so
    raw cosines are crowded; centred, a window's 1st and 10th nearest training tracks are 0.83 and 0.73 apart from a
    median of 0):
      neighbours       for each window, a softmax over its centred cosine to every other training track (the teacher's
                       track vectors, fixed), at temperature tau; KL(teacher || student). At tau 0.05 the teacher puts
                       ~63 % of the weight on the 10 nearest tracks, so the loss is about which tracks are nearest:
                       the thing top-10 overlap measures (as in CompRess / SEED, with teacher tracks as anchors).
      batch-relations  the classic relational distillation (Park et al. 2019, RKD angle-free form): the squared
                       difference of the centred cosine matrices of the batch, off the diagonal. Few pairs per batch
                       are close, so it mostly teaches the coarse layout.
    total = window term + weight * relational part."""
    import torch
    import torch.nn.functional as F
    if kind == 'cosine':
        def loss(prediction, target, index):
            window = (1 - F.cosine_similarity(prediction, target, dim=-1)).mean()
            return window, {'window': window.item()}
        return loss
    teacher = unit(data['train']['teacher'])
    mean = torch.from_numpy(teacher.mean(0)).to(device)

    def centred(v):
        return F.normalize(F.normalize(v, dim=-1) - mean, dim=-1)

    if kind == 'cosine+batch-relations':
        def relational(prediction, target, index):
            student, teach = centred(prediction), centred(target)
            off = ~torch.eye(len(student), dtype=torch.bool, device=student.device)
            return ((student @ student.T - teach @ teach.T)[off] ** 2).mean()
    elif kind == 'cosine+neighbours':
        _, own = np.unique(data['train']['tracks'], return_inverse=True)
        sums = np.zeros((own.max() + 1, teacher.shape[1]), dtype=np.float64)
        np.add.at(sums, own, teacher)
        anchors = centred(torch.from_numpy(unit(sums).astype(np.float32)).to(device))
        own = torch.from_numpy(own).to(device)

        def relational(prediction, target, index):
            mask = F.one_hot(own[index], len(anchors)).bool()     # a window is not its own track's neighbour

            def log_p(v):   # finite fill, not -inf: exp underflows to exactly 0 and no NaN reaches the gradient
                return F.log_softmax((centred(v) @ anchors.T / tau).masked_fill(mask, -1e4), dim=-1)
            with torch.no_grad():
                teacher_log = log_p(target)
            return (teacher_log.exp() * (teacher_log - log_p(prediction))).sum(-1).mean()
    else:
        raise ValueError(kind)

    def loss(prediction, target, index):
        window = (1 - F.cosine_similarity(prediction, target, dim=-1)).mean()
        extra = relational(prediction, target, index)
        return window + weight * extra, {'window': window.item(), 'relational': extra.item()}
    return loss


def train_student(name, data, args, mlflow, log):
    import torch
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
    loss_fn = make_loss(args.loss, data, device, args.aux_weight, args.tau)
    val_target = unit(data['val']['teacher'])
    val_tracks = data['val']['tracks']
    val_teacher_tracks, _ = track_vectors(data['val']['teacher'], val_tracks)
    rng = np.random.default_rng(args.seed)
    check_rows = None
    if args.eval_train:   # a fixed sample, drawn apart from the training order
        check_rows = np.sort(np.random.default_rng(args.seed + 1).choice(
            len(train_mel), min(4096, len(train_mel)), replace=False))
    # The best epoch by each rule; --select decides which one is used (and early stopping), the other is reported.
    best = {rule: {'value': -1.0, 'epoch': 0, 'state': None} for rule in SELECT_RULES}
    for epoch in range(1, args.max_epochs + 1):
        model.train()
        started, losses, parts = time.time(), [], {}
        order = rng.permutation(len(train_mel))
        for start in range(0, len(order) - args.batch + 1, args.batch):   # drop the last partial batch (BatchNorm)
            index = np.sort(order[start:start + args.batch])
            x = torch.from_numpy(train_mel[index]).to(device, non_blocking=True).float()
            with torch.autocast(device, dtype=torch.float16, enabled=amp):
                prediction = model.embed_mel(x)
            index_t = torch.from_numpy(index).to(device)
            loss, part = loss_fn(prediction.float(), train_target[index_t], index_t)
            optimizer.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            if scheduler is not None:
                scheduler.step()
            losses.append(loss.item())
            for key, value in part.items():
                parts.setdefault(key, []).append(value)
        val_prediction = predict(model, val_mel, device, amp)
        val_cos = float((unit(val_prediction) * val_target).sum(1).mean())
        if not np.isfinite(val_cos):
            sys.exit(f'epoch {epoch}: validation cosine is {val_cos} (NaN in training?)')
        val_top10 = top_k_overlap(track_vectors(val_prediction, val_tracks)[0], val_teacher_tracks)
        metrics = {'train_loss': float(np.mean(losses)), 'val_cos': val_cos, 'val_top10': val_top10,
                   'epoch_s': time.time() - started, 'lr': optimizer.param_groups[0]['lr'],
                   **({f'train_loss_{key}': float(np.mean(value)) for key, value in parts.items()}
                      if len(parts) > 1 else {})}
        if check_rows is not None:
            metrics['train_cos'] = float((unit(predict(model, train_mel[check_rows], device, amp))
                                          * train_unit[check_rows]).sum(1).mean())
        mlflow.log_metrics(metrics, step=epoch)
        marks = []
        for rule in SELECT_RULES:
            if metrics[rule] > best[rule]['value']:
                best[rule] = {'value': metrics[rule], 'epoch': epoch, 'val_cos': val_cos, 'val_top10': val_top10,
                              'state': {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}}
                marks.append(rule)
        log(f'epoch {epoch:2d}: train loss {np.mean(losses):.4f}'
            + ''.join(f', {key} {np.mean(value):.4f}' for key, value in parts.items() if len(parts) > 1) + ', '
            + (f'train cosine {metrics["train_cos"]:.4f}, ' if check_rows is not None else '')
            + f'val cosine {val_cos:.4f}, val top-10 {val_top10:.3f}'
            + (f' (best {", ".join(marks)})' if marks else '') + f', {time.time() - started:.0f} s')
        if epoch - best[args.select]['epoch'] >= args.patience:
            log(f'early stop: no better {args.select} for {args.patience} epochs')
            break
    if device == 'cuda':
        peak = torch.cuda.max_memory_allocated() / 1e6
        mlflow.log_metric('gpu_peak_mb', peak)
        log(f'peak GPU memory {peak:.0f} MB')
    test_mel = mel_of(data, 'test')
    test_teacher_tracks, _ = track_vectors(data['test']['teacher'], data['test']['tracks'])
    for rule in SELECT_RULES:   # what each selection rule would have given on test (the chosen one in full below)
        if rule != args.select:
            model.load_state_dict(best[rule]['state'])
            other = predict(model, test_mel, device, amp)
            mlflow.log_metrics({
                f'if_{rule}_best_epoch': best[rule]['epoch'],
                f'if_{rule}_test_top10_overlap': top_k_overlap(track_vectors(other, data['test']['tracks'])[0],
                                                               test_teacher_tracks),
                f'if_{rule}_test_window_cos_mean': float((unit(other) * unit(data['test']['teacher'])).sum(1).mean())})
    chosen = best[args.select]
    model.load_state_dict(chosen['state'])
    predictions = {'val': predict(model, val_mel, device, amp), 'test': predict(model, test_mel, device, amp)}
    return model.cpu(), chosen, predictions


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
    parser.add_argument('--question', help="MLflow tag grouping runs by the question they answer, e.g. 'structure'")
    parser.add_argument('--loss', choices=LOSSES, default='cosine', help='see make_loss')
    parser.add_argument('--aux-weight', type=float, default=1.0, help='weight of the relational part of --loss')
    parser.add_argument('--tau', type=float, default=0.05, help='softmax temperature of --loss cosine+neighbours')
    parser.add_argument('--all-windows', action='store_true',
                        help='train on every window of the training tracks, not only the 16 cached ones')
    parser.add_argument('--select', choices=SELECT_RULES, default='val_cos',
                        help='the best epoch by validation cosine or by validation top-10 overlap (also early '
                             'stopping); the other rule\'s test result is logged as if_<rule>_*')
    args = parser.parse_args()

    def log(message):
        print(message, flush=True)

    kind = 'baseline' if args.student in BASELINES else 'student'
    n_mels = STUDENTS[args.student]().n_mels if kind == 'student' else 64
    data = load_data(args.train_tracks, args.seed, n_mels, args.all_windows)
    mlflow = mlflow_experiment(args.experiment)
    name = f"{args.student}-n{data['train_track_count']}" + (f'-{args.name_suffix}' if args.name_suffix else '')
    tags = {'phase': args.phase, 'kind': kind, **({'question': args.question} if args.question else {})}
    with mlflow.start_run(run_name=name, tags=tags):
        log_code_state(mlflow)
        mlflow.log_params({'student': args.student, 'train_tracks': data['train_track_count'],
                           'train_windows': len(data['train']['tracks']), 'val_windows': len(data['val']['rows']),
                           'test_windows': len(data['test']['rows']), 'manifest_sha': data['manifest_sha'],
                           'seed': args.seed, 'n_mels': n_mels, 'all_windows': args.all_windows})
        started = time.time()
        if kind == 'baseline':
            predictions = fit_baseline(args.student, data, log)
            if 'alpha' in predictions:
                mlflow.log_param('ridge_alpha', predictions['alpha'])
        else:
            mlflow.log_params({'lr': args.lr, 'weight_decay': args.weight_decay, 'batch': args.batch,
                               'max_epochs': args.max_epochs, 'patience': args.patience, 'optimizer': 'AdamW',
                               'schedule': args.schedule, 'select': args.select,
                               'loss': '1 - cosine' if args.loss == 'cosine' else args.loss,
                               **({'aux_weight': args.aux_weight} if args.loss != 'cosine' else {}),
                               **({'tau': args.tau} if args.loss == 'cosine+neighbours' else {}),
                               'amp': args.amp, 'eval_train': args.eval_train})
            model, best, predictions = train_student(args.student, data, args, mlflow, log)
            mlflow.log_metrics({'best_epoch': best['epoch'], 'best_val_cos': best['val_cos'],
                                'best_val_top10': best['val_top10'],
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

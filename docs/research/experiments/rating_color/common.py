"""Shared code for the rating / colour prediction experiments (see docs/research/rating_color_plan.md).

Runs with the system Python (numpy, scikit-learn), not the app's .venv. It only reads the app's
data: a snapshot copy is taken first, so the app (closed or not) is never touched.

Every embedding model is reduced to ONE vector per track (a row of `Vectors.matrix`), so all
models go through the same probes and the same validation.
"""
import hashlib
import re
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[4]
CACHE = REPO / '.research_cache'
sys.path.insert(0, str(REPO / 'src'))


def snapshot_data(app_dir, refresh=False):
    """Copy the app's database files to .research_cache/snapshot (read-only use of the originals)."""
    target = CACHE / 'snapshot'
    if target.exists() and not refresh:
        return target
    target.mkdir(parents=True, exist_ok=True)
    for name in ('library.sqlite', 'embeddings.sqlite', 'embeddings.sqlite-wal', 'embeddings.sqlite-shm',
                 'embeddings.sqlite-x-embeddings-1-data.bin'):
        source = Path(app_dir) / name
        if source.exists():
            shutil.copy2(source, target / name)
    return target


@dataclass
class Vectors:
    keys: list          # path_key per row
    matrix: np.ndarray  # (n, d), float32


def cnn14_vectors(snapshot):
    """The app's own track vector: mean + std of the 5 s CNN14 embeddings, centred, unit length."""
    from traktor_key_calculator.core.embeddings import EmbeddingStore
    from traktor_key_calculator.core.similarity import track_vectors
    matrices = EmbeddingStore(snapshot / 'embeddings.sqlite').load_many()
    keys = sorted(matrices)
    return Vectors(keys, track_vectors([matrices[key] for key in keys]))


def load_vectors(model, snapshot):
    """'cnn14' from the app's store; any other model from .research_cache/vectors/<model>.npz."""
    if model == 'cnn14':
        return cnn14_vectors(snapshot)
    data = np.load(CACHE / 'vectors' / f'{model}.npz', allow_pickle=False)
    return Vectors(data['keys'].tolist(), data['matrix'].astype(np.float32))


def save_vectors(model, vectors):
    (CACHE / 'vectors').mkdir(parents=True, exist_ok=True)
    np.savez(CACHE / 'vectors' / f'{model}.npz', keys=np.array(vectors.keys), matrix=vectors.matrix)


def _artist_group(artist, path):
    """Same artist = same group, so near-identical tracks (remixes, same album) never sit in both
    the training and the test part. Without an artist tag the folder is the group."""
    artist = re.sub(r'\s+', ' ', (artist or '').strip().lower())
    return 'artist:' + artist if artist else 'folder:' + str(Path(path).parent).lower()


def load_labels(snapshot, keys):
    """Per row of `keys`: Traktor rating (1-5, 0 = none), Traktor colour (1-7, 0 = none), group."""
    connection = sqlite3.connect(snapshot / 'library.sqlite')
    rows = {key: (rating, color, artist, path) for key, rating, color, artist, path in connection.execute(
        'SELECT path_key, rating, color, artist, file_path FROM tracks')}
    rating = np.array([int(rows[key][0] or 0) for key in keys])
    colour = np.array([int(rows[key][1] or 0) for key in keys])
    groups = np.array([_artist_group(rows[key][2], rows[key][3]) for key in keys])
    return rating, colour, groups


def locked_test(groups):
    """True for the ~20 % of artist groups reserved as the FINAL test set. Model and setting choices
    are made on the other 80 % only; the locked part is evaluated once, for the chosen setup
    (`evaluate.py --final`). Stable: a group's side never changes (hash of its name)."""
    return np.array([int(hashlib.md5(g.encode('utf-8')).hexdigest(), 16) % 5 == 0 for g in groups])


def fold_splits(y, groups, folds=5, repeats=3):
    """[(train_index, test_index)]: stratified, grouped by artist, `repeats` different shuffles."""
    from sklearn.model_selection import StratifiedGroupKFold
    for seed in range(repeats):
        yield from StratifiedGroupKFold(folds, shuffle=True, random_state=seed).split(np.zeros(len(y)), y, groups)


def probe_scores(name, x_train, y_train, x_test):
    """Class probabilities of the test rows: (n_test, n_classes) in sorted class order.
    Probes are deliberately simple: with ~2,000 labels a bigger head only memorises."""
    classes = np.unique(y_train)
    if name == 'majority':
        prior = np.array([(y_train == c).mean() for c in classes])
        return np.tile(prior, (len(x_test), 1)), classes
    if name == 'logistic':
        from sklearn.decomposition import PCA
        from sklearn.linear_model import LogisticRegression
        pca = PCA(min(100, len(x_train) - 1, x_train.shape[1]), random_state=0).fit(x_train)
        model = LogisticRegression(C=0.3, max_iter=3000).fit(pca.transform(x_train), y_train)
        return model.predict_proba(pca.transform(x_test)), model.classes_
    if name == 'knn':
        scores = x_test @ x_train.T
        top = np.argsort(-scores, axis=1)[:, :15]
        out = np.zeros((len(x_test), len(classes)))
        for row, neighbours in enumerate(top):
            weights = np.maximum(scores[row, neighbours], 1e-3)
            for neighbour, weight in zip(neighbours, weights):
                out[row, np.searchsorted(classes, y_train[neighbour])] += weight
        return out / out.sum(1, keepdims=True), classes
    raise ValueError(name)


def cross_validated(name, matrix, y, groups, folds=5, repeats=3):
    """Out-of-fold class probabilities averaged over the repeats: (n, n_classes), classes."""
    classes = np.unique(y)
    total, count = np.zeros((len(y), len(classes))), np.zeros(len(y))
    for train, test in fold_splits(y, groups, folds, repeats):
        proba, seen = probe_scores(name, matrix[train], y[train], matrix[test])
        columns = np.searchsorted(classes, seen)
        total[np.ix_(test, columns)] += proba
        count[test] += 1
    return total / count[:, None], classes


def bootstrap(metric, *arrays, rounds=400, seed=0):
    """(value, low, high): the metric on all rows and its 95 % interval over resampled rows."""
    rng = np.random.default_rng(seed)
    n = len(arrays[0])
    values = []
    for _ in range(rounds):
        pick = rng.integers(0, n, n)
        try:
            values.append(metric(*(a[pick] for a in arrays)))
        except ValueError:  # a resample missing a class
            continue
    return metric(*arrays), float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))


def precision_at_coverage(truth, score, coverage=0.2):
    """Of the `coverage` share of tracks with the highest score, how many really are the class."""
    top = np.argsort(-score)[:max(1, int(round(len(score) * coverage)))]
    return float(np.mean(truth[top]))


def fmt(value, low=None, high=None, percent=True):
    scale = 100 if percent else 1
    text = f'{value * scale:.0f}' if percent else f'{value:.2f}'
    if low is not None:
        text += f' ({low * scale:.0f}-{high * scale:.0f})' if percent else f' ({low:.2f}-{high:.2f})'
    return text + (' %' if percent else '')

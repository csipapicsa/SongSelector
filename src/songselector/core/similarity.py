"""Track similarity from the stored CNN14 embeddings, and a 2D map of the library.

Per-track vector (track_vectors): the mean and standard deviation of a track's 5 s
embeddings, centred on the library average. Measured on the developer's library
(2026-10-27, 460 tracks, folders as a stand-in for style): among a track's 10 most
similar tracks, 92 % were from the same folder (DnB) and 89 % for the minority style
(breakbeat, 11 % of tracks). The plain mean scored 98 % / 81 %. Keep the choice in this
one function, so it can be re-evaluated once more styles are analysed.

Map (tsne_layout): t-SNE in plain numpy (no scikit-learn in the exe). On the same data,
t-SNE kept 46-47 % of each track's 10 true nearest neighbours as map neighbours, UMAP
37-42 %, PCA 26 %. Because any 2D map distorts, use nearest() for "most similar" lists;
the map is for overview.
"""
import numpy as np

PERPLEXITY = 30.0


def track_vectors(matrices):
    """(n_tracks, 4096) vectors from a list of (frames, 2048) embedding matrices."""
    if not matrices:
        return np.zeros((0, 4096), dtype=np.float32)
    raw = np.stack([np.concatenate([m.mean(0), m.std(0)]) for m in (np.asarray(x, np.float32) for x in matrices)])
    centred = raw - raw.mean(0)
    norms = np.linalg.norm(centred, axis=1, keepdims=True)
    return (centred / np.where(norms == 0, 1, norms)).astype(np.float32)


def nearest(vectors, index, count=10, among=None):
    """[(row, cosine similarity)] of the `count` most similar rows to vectors[index].

    among: optional row indices to choose from (e.g. the tracks visible after filtering).
    """
    candidates = np.arange(len(vectors)) if among is None else np.asarray(list(among), dtype=int)
    candidates = candidates[candidates != index]
    if not len(candidates):
        return []
    scores = vectors[candidates] @ vectors[index]
    order = np.argsort(-scores)[:count]
    return [(int(candidates[i]), float(scores[i])) for i in order]


def _pca(data, dims):
    centred = data - data.mean(0)
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    return centred @ vt[:dims].T


def _affinities(distances, perplexity, steps=64):
    """Symmetric t-SNE input probabilities; per-row Gaussian widths by bisection on beta."""
    n = len(distances)
    target = np.log(perplexity)
    beta = np.ones(n)
    low, high = np.full(n, -np.inf), np.full(n, np.inf)
    off_diagonal = ~np.eye(n, dtype=bool)
    for _ in range(steps):
        p = np.exp(-distances * beta[:, None]) * off_diagonal
        total = np.maximum(p.sum(1), 1e-12)
        entropy = np.log(total) + beta * (distances * p).sum(1) / total
        too_flat = entropy > target              # entropy too high -> narrower Gaussian
        low = np.where(too_flat, beta, low)
        high = np.where(too_flat, high, beta)
        beta = np.where(np.isinf(high), beta * 2, np.where(np.isinf(low), beta / 2, (low + high) / 2))
    p = p / total[:, None]
    p = (p + p.T) / (2 * n)
    return np.maximum(p, 1e-12)


def tsne_layout(vectors, perplexity=PERPLEXITY, iterations=750, seed=0, should_stop=lambda: False, dims=2):
    """(n, dims) map coordinates (2D map or 3D view); similar tracks end up close together.

    Exact t-SNE (van der Maaten & Hinton 2008) with PCA initialisation, early
    exaggeration and adaptive gains, as in scikit-learn's defaults. O(n^2) memory and
    time: about a minute for 3,000 tracks; run it in the background and cache it.
    """
    n = len(vectors)
    if n < 3:
        return np.zeros((n, dims), dtype=np.float32)
    data = _pca(np.asarray(vectors, np.float64), min(50, n - 1, vectors.shape[1]))
    squared = (data ** 2).sum(1)
    distances = np.maximum(squared[:, None] + squared[None, :] - 2 * data @ data.T, 0)
    p = _affinities(distances / np.median(distances[distances > 0]), min(perplexity, (n - 1) / 3))

    y = _pca(data, dims)
    y = y / max(y[:, 0].std(), 1e-12) * 1e-4
    rng = np.random.default_rng(seed)
    y += rng.normal(0, 1e-6, y.shape)
    # The n x n work below runs in float32: half the memory and about twice as fast,
    # and map coordinates need no more precision.
    y, p = y.astype(np.float32), p.astype(np.float32)
    velocity, gains = np.zeros_like(y), np.ones_like(y)
    rate = np.float32(max(n / 12 / 4, 50))
    for step in range(iterations):
        if should_stop():
            return None
        exaggeration, momentum = (np.float32(12), 0.5) if step < 250 else (np.float32(1), 0.8)
        sq = (y ** 2).sum(1)
        num = 1 / (1 + np.maximum(sq[:, None] + sq[None, :] - 2 * (y @ y.T), 0))
        np.fill_diagonal(num, 0)
        q = np.maximum(num / num.sum(), np.float32(1e-12))
        weights = (exaggeration * p - q) * num
        gradient = 4 * (weights.sum(1)[:, None] * y - weights @ y)
        same_sign = np.sign(gradient) == np.sign(velocity)
        gains = np.maximum(np.where(same_sign, gains * 0.8, gains + 0.2), 0.01)
        velocity = momentum * velocity - rate * gains * gradient
        y = y + velocity
    return (y - y.mean(0)).astype(np.float32)


def place_new(known_points, known_vectors, new_vectors, neighbours=5):
    """Map positions for tracks analysed after the last layout: the similarity-weighted
    average position of their most similar already-placed tracks (instant, no t-SNE)."""
    dims = np.asarray(known_points).shape[1] if len(known_points) else 2
    if not len(new_vectors):
        return np.zeros((0, dims), dtype=np.float32)
    if not len(known_vectors):
        return np.zeros((len(new_vectors), dims), dtype=np.float32)
    scores = np.asarray(new_vectors) @ np.asarray(known_vectors).T
    count = min(neighbours, scores.shape[1])
    top = np.argsort(-scores, axis=1)[:, :count]
    weights = np.maximum(np.take_along_axis(scores, top, axis=1), 1e-3)
    return ((known_points[top] * weights[..., None]).sum(1) / weights.sum(1, keepdims=True)).astype(np.float32)


# Map edges: which relations between two tracks can be drawn. Values are the track's
# table texts (as shown in the list, so keys are the tempo-adjusted ones).
EDGE_SAME_COLOR = 'same_color'
EDGE_SAME_RATING = 'same_rating'


def display_color(fields):
    """Colour number of a dot: the Song Selector colour first, then Traktor's; 0 = none."""
    for name in ('Color - Song Selector', 'Color'):
        try:
            number = int(float(fields.get(name) or 0))
        except ValueError:
            number = 0
        if number:
            return number
    return 0


def connection(from_fields, to_fields, criteria):
    """The first enabled reason to connect two tracks, or None.

    criteria: names of harmonic mix types (core.harmonic.MIX_TYPES, compared on the
    tempo-adjusted Camelot key), EDGE_SAME_COLOR and/or EDGE_SAME_RATING.
    """
    from songselector.core.harmonic import mix_type
    mix = mix_type(from_fields.get('Camelot Key New'), to_fields.get('Camelot Key New'))
    if mix is not None and mix.name in criteria:
        return mix.name
    if EDGE_SAME_COLOR in criteria and display_color(from_fields) and \
            display_color(from_fields) == display_color(to_fields):
        return EDGE_SAME_COLOR
    if EDGE_SAME_RATING in criteria:
        def rating(fields):
            return fields.get('Rating - Song Selector') or fields.get('Rating') or ''
        if rating(from_fields) and rating(from_fields) == rating(to_fields):
            return EDGE_SAME_RATING
    return None

"""Track similarity from the stored CNN14 embeddings, and a 2D map of the library.

Per-track vector (track_vectors): the mean and standard deviation of a track's 5 s
embeddings, centred on the library average. Measured on the developer's library
(2026-10-27, 460 tracks, folders as a stand-in for style): among a track's 10 most
similar tracks, 92 % were from the same folder (DnB) and 89 % for the minority style
(breakbeat, 11 % of tracks). The plain mean scored 98 % / 81 %. Keep the choice in this
one function, so it can be re-evaluated once more styles are analysed.

Map (PROJECTIONS: tsne_layout, umap_layout, pca_layout): plain numpy (no scikit-learn or
numba in the exe). On the same data, t-SNE kept 46-47 % of each track's 10 true nearest
neighbours as map neighbours, UMAP 37-42 %, PCA 26 %. Again 2026-11-24 on 3,411 LAION CLAP
tracks (kept / Spearman rho of pair distances, i.e. global structure / seconds), 3,000 tracks:
t-SNE 35 % / 0.50 / 142 s, UMAP 22 % / 0.56 / 6 s (umap-learn 24 % / 0.54), PCA 7 % / 0.60 /
instant; 100 tracks: t-SNE 53 %, UMAP 57 % (umap-learn 57 %), PCA 34 %. Because any 2D map
distorts, use nearest() for "most similar" lists; the map is for overview.
"""
import numpy as np

PERPLEXITY = 30.0


def raw_vectors(matrices):
    """(n_tracks, 2 * dim) mean and std of each (frames, dim) embedding matrix, not yet centred."""
    return np.stack([np.concatenate([m.mean(0), m.std(0)]) for m in (np.asarray(x, np.float32) for x in matrices)])


def centred_unit(raw, centre):
    """Raw vectors minus `centre` (the mean of the tracks a map was built from), at unit length."""
    centred = raw - centre
    norms = np.linalg.norm(centred, axis=1, keepdims=True)
    return (centred / np.where(norms == 0, 1, norms)).astype(np.float32)


def track_vectors(matrices, with_centre=False):
    """(n_tracks, 4096) vectors from a list of (frames, 2048) embedding matrices: centred on these tracks, unit
    length. with_centre: also return the centre, to place more tracks later in the same space (centred_unit)."""
    if not matrices:
        empty = np.zeros((0, 4096), dtype=np.float32)
        return (empty, None) if with_centre else empty
    raw = raw_vectors(matrices)
    centre = raw.mean(0)
    vectors = centred_unit(raw, centre)
    return (vectors, centre) if with_centre else vectors


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


def _top_components(data, dims, seed=0, power_steps=4):
    """Projection of `data` (centred here) on its first `dims` principal axes: randomized SVD (Halko et al. 2011),
    seconds instead of minutes for 5,000 x 4,096. Signs fixed (each axis's largest score is positive), so the same
    tracks give the same picture, not a mirrored one."""
    centred = np.asarray(data, np.float32)
    centred = centred - centred.mean(0)
    rank = min(dims + 10, *centred.shape)
    basis = centred @ np.random.default_rng(seed).normal(size=(centred.shape[1], rank)).astype(np.float32)
    for _ in range(power_steps):  # sharpens the leading axes; QR keeps the iteration numerically stable
        basis, _ = np.linalg.qr(basis)
        basis, _ = np.linalg.qr(centred.T @ basis)
        basis = centred @ basis
    basis, _ = np.linalg.qr(basis)
    left, values, _ = np.linalg.svd(basis.T @ centred, full_matrices=False)
    scores = (basis @ left[:, :dims]) * values[:dims]
    if scores.shape[1] < dims:  # fewer tracks than dimensions: the missing axes are flat
        scores = np.hstack([scores, np.zeros((len(scores), dims - scores.shape[1]), scores.dtype)])
    signs = np.sign(scores[np.abs(scores).argmax(0), np.arange(dims)])
    return (scores * np.where(signs == 0, 1, signs)).astype(np.float32)


def pca_layout(vectors, should_stop=lambda: False, dims=2):
    """(n, dims) map coordinates: the first principal axes of the track vectors. Instant and linear, so distances
    between far-apart groups mean something (t-SNE and UMAP do not keep them), but neighbours mix more."""
    vectors = np.asarray(vectors, np.float32)
    if len(vectors) < 2:
        return np.zeros((len(vectors), dims), dtype=np.float32)
    return None if should_stop() else _top_components(vectors, dims)


# UMAP (McInnes, Healy & Melville 2018) with umap-learn's defaults: 15 neighbours, min_dist 0.1, spread 1, 5 negative
# samples per edge. a and b fit the curve 1 / (1 + a d^2b) to min_dist 0.1 (umap-learn's find_ab_params).
UMAP_NEIGHBOURS = 15
UMAP_A, UMAP_B = 1.5769, 0.8951
UMAP_NEGATIVES = 5


def _nearest_neighbours(vectors, count, should_stop, block=1024):
    """(indexes, distances), each (n, count): every row's `count` nearest other rows, nearest first. Exact, in
    blocks of rows, so memory stays at block x n."""
    n = len(vectors)
    squared = (vectors ** 2).sum(1)
    indexes = np.empty((n, count), dtype=np.int64)
    distances = np.empty((n, count), dtype=np.float32)
    for start in range(0, n, block):
        if should_stop():
            return None
        stop = min(start + block, n)
        part = squared[start:stop, None] + squared[None, :] - 2 * (vectors[start:stop] @ vectors.T)
        part[np.arange(stop - start), np.arange(start, stop)] = np.inf  # not its own neighbour
        nearest_rows = np.argpartition(part, count - 1, axis=1)[:, :count]
        near = np.take_along_axis(part, nearest_rows, 1)
        order = np.argsort(near, 1)
        indexes[start:stop] = np.take_along_axis(nearest_rows, order, 1)
        distances[start:stop] = np.sqrt(np.maximum(np.take_along_axis(near, order, 1), 0))
    return indexes, distances


def _fuzzy_graph(indexes, distances, steps=64):
    """UMAP's neighbour graph as (heads, tails, weights), both directions of each edge: per track, weights
    exp(-(d - d_nearest) / sigma) with sigma chosen so they sum to log2(k); then w + w' - w w' over both directions."""
    n, count = indexes.shape
    rho = distances[:, 0]
    excess = np.maximum(distances - rho[:, None], 0).astype(np.float64)
    target = np.log2(count)
    low, high, sigma = np.zeros(n), np.full(n, np.inf), np.ones(n)
    for _ in range(steps):
        total = np.exp(-excess / sigma[:, None]).sum(1)
        too_wide = total > target
        high = np.where(too_wide, sigma, high)
        low = np.where(too_wide, low, sigma)
        sigma = np.where(np.isinf(high), sigma * 2, (low + high) / 2)
    sigma = np.maximum(sigma, 1e-3 * max(float(distances.mean()), 1e-12))
    weights = np.exp(-excess / sigma[:, None]).ravel()
    heads, tails = np.repeat(np.arange(n), count), indexes.ravel()
    keys, inverse = np.unique(np.concatenate([heads * n + tails, tails * n + heads]), return_inverse=True)
    forward = np.bincount(inverse[:len(weights)], weights, len(keys))   # w(i -> j)
    backward = np.bincount(inverse[len(weights):], weights, len(keys))  # w(j -> i)
    return keys // n, keys % n, forward + backward - forward * backward


def umap_layout(vectors, neighbours=UMAP_NEIGHBOURS, epochs=None, seed=0, should_stop=lambda: False, dims=2):
    """(n, dims) map coordinates with UMAP: keeps each track's nearest neighbours, as t-SNE does, and more of the
    larger structure (which groups sit next to each other). Plain numpy (no umap-learn: it needs numba).

    Exact nearest neighbours (as nearest() ranks them), PCA initialisation, and umap-learn's optimiser with one
    difference: each epoch applies all its edge updates at once (vectorized, as GPU versions do) instead of one
    edge after another."""
    vectors = np.asarray(vectors, np.float32)
    n = len(vectors)
    if n < 3:
        return np.zeros((n, dims), dtype=np.float32)
    epochs = epochs or (500 if n <= 10_000 else 200)
    found = _nearest_neighbours(vectors, min(neighbours, n - 1), should_stop)
    if found is None:
        return None
    heads, tails, weights = _fuzzy_graph(*found)
    keep = weights >= weights.max() / epochs  # edges too weak to be sampled once
    heads, tails, weights = heads[keep], tails[keep], weights[keep]
    every = weights.max() / weights           # an edge is sampled every this many epochs
    next_sample = every.copy()

    rng = np.random.default_rng(seed)
    y = _top_components(vectors, dims, seed)
    y = 10 * y / max(float(np.abs(y).max()), 1e-12) + rng.normal(0, 1e-4, y.shape).astype(np.float32)
    a, b = np.float32(UMAP_A), np.float32(UMAP_B)
    for epoch in range(epochs):
        if should_stop():
            return None
        due = next_sample <= epoch + 1
        next_sample[due] += every[due]
        head, tail = heads[due], tails[due]
        rate = np.float32(1 - epoch / epochs)
        step = np.zeros_like(y)
        with np.errstate(divide='ignore', invalid='ignore', over='ignore'):  # d = 0 gives inf * 0: masked out
            # Attraction along the sampled edges, both ends move.
            offset = y[head] - y[tail]
            squared = (offset ** 2).sum(1, keepdims=True)
            pull = -2 * a * b * squared ** (b - 1) / (a * squared ** b + 1)
            pull = np.clip(np.where(squared > 0, pull * offset, 0), -4, 4) * rate
            # Repulsion from random tracks, only the head moves.
            repelled = np.repeat(head, UMAP_NEGATIVES)
            offset = y[repelled] - y[rng.integers(0, n, len(repelled))]
            squared = (offset ** 2).sum(1, keepdims=True)
            push = 2 * b / ((0.001 + squared) * (a * squared ** b + 1))
            push = np.where(squared > 0, np.clip(push * offset, -4, 4), 0) * rate
        for axis in range(dims):
            step[:, axis] = (np.bincount(head, pull[:, axis], n) - np.bincount(tail, pull[:, axis], n)
                             + np.bincount(repelled, push[:, axis], n))
        y += step
    return (y - y.mean(0)).astype(np.float32)


# The map's layouts: setting `Map projection`, in the Layout box's order. UMAP is the default since 2026-11-24 (the
# user found it separates the library better, and it takes seconds instead of minutes); t-SNE was before.
PROJECTIONS = {
    'umap': ('UMAP', umap_layout),
    'tsne': ('t-SNE', tsne_layout),
    'pca': ('PCA', pca_layout),
}
DEFAULT_PROJECTION = 'umap'


def project(vectors, projection=DEFAULT_PROJECTION, should_stop=lambda: False, dims=2):
    """(n, dims) map coordinates with the named layout (PROJECTIONS); None if stopped."""
    _, layout = PROJECTIONS.get(projection, PROJECTIONS[DEFAULT_PROJECTION])
    return layout(vectors, should_stop=should_stop, dims=dims)


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
    """Colour of a dot: the Song Selector colour first, then the DJ program's / the tags'. A family number or a
    program's exact '#RRGGBB' (core/track_colors.py); 0 = none. Equal values mean "same colour" on the map."""
    from songselector.core.track_colors import normalize
    for name in ('Color - Song Selector', 'Color'):
        colour = normalize(fields.get(name))
        if colour:
            return colour
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

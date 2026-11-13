"""Unsupervised grouping of tracks, for colouring the similarity map by group.

Three methods to compare (numpy only; the exe has no scikit-learn). Each has one parameter:
- kmeans: spherical k-means on the track vectors (cosine). Parameter: number of groups.
- communities: Louvain modularity on the graph that links each track to its most similar
  tracks. It follows neighbours rather than gaps, so it can split a blob that looks
  uniform. Parameter: resolution (higher: more, smaller groups).
- density: DBSCAN on the 2D map positions, so it groups the clumps the eye sees. Tracks in
  thin areas and tiny clumps stay ungrouped (-1). Parameter: share of tracks (%) that count
  as dense.

group_tracks() numbers groups by size: 0 is the largest.

Measured on the developer's library (2026-10-28, 3,489 tracks; style from genre/folder:
DnB 1,262, breaks 1,057, house 380): each method takes about 1 s. Style purity of the groups
0.75-0.77 for k-means (8) and communities (1.0), 0.83 for map density, against 0.47 for a
single group; a track's 10 nearest neighbours share its style 81 % of the time. DnB forms
clean groups; breaks and house mix.
"""
from dataclasses import dataclass

import numpy as np

NEIGHBOURS = 10      # links per track in the communities graph
DENSE_NEIGHBOURS = 8  # DBSCAN min_samples


@dataclass(frozen=True)
class GroupingMethod:
    name: str
    label: str
    parameter: str     # what the parameter means, for the UI
    minimum: float
    maximum: float
    step: float
    default: float
    decimals: int


GROUPING_METHODS = [
    GroupingMethod('kmeans', 'k-means', 'groups', 2, 40, 1, 8, 0),
    GroupingMethod('communities', 'Neighbour communities', 'resolution', 0.1, 5, 0.1, 1.0, 1),
    GroupingMethod('density', 'Map density', 'dense %', 5, 95, 5, 60, 0),
]
GROUPING_BY_NAME = {method.name: method for method in GROUPING_METHODS}


def _unit(vectors):
    vectors = np.asarray(vectors, np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


def kmeans(vectors, groups, seed=0, iterations=100):
    """Spherical k-means (cosine similarity to unit-length centres), k-means++ start."""
    x = _unit(vectors)
    n = len(x)
    groups = int(max(1, min(groups, n)))
    rng = np.random.default_rng(seed)
    centres = np.empty((groups, x.shape[1]), np.float32)
    centres[0] = x[rng.integers(n)]
    distance = 1 - x @ centres[0]       # squared euclidean distance / 2, for unit vectors
    for index in range(1, groups):
        weights = np.clip(distance, 0, None)
        chosen = rng.choice(n, p=weights / weights.sum()) if weights.sum() > 0 else rng.integers(n)
        centres[index] = x[chosen]
        distance = np.minimum(distance, 1 - x @ centres[index])
    labels = None
    for _ in range(iterations):
        new = np.argmax(x @ centres.T, axis=1)
        if labels is not None and np.array_equal(new, labels):
            break
        labels = new
        for index in range(groups):
            total = x[labels == index].sum(0)
            norm = np.linalg.norm(total)
            if norm > 0:
                centres[index] = total / norm
    return labels


def knn_graph(vectors, neighbours=NEIGHBOURS, chunk=512):
    """Symmetric graph as a list of {node: weight}: each track linked to its most similar
    tracks (cosine); weight 2 when both chose each other."""
    x = _unit(vectors)
    n = len(x)
    neighbours = min(neighbours, n - 1)
    graph = [dict() for _ in range(n)]
    if neighbours < 1:
        return graph
    for start in range(0, n, chunk):
        scores = x[start:start + chunk] @ x.T
        scores[np.arange(len(scores)), np.arange(start, start + len(scores))] = -np.inf
        for offset, row in enumerate(np.argpartition(-scores, neighbours, axis=1)[:, :neighbours]):
            node = start + offset
            for other in row.tolist():
                graph[node][other] = graph[node].get(other, 0) + 1
                graph[other][node] = graph[other].get(node, 0) + 1
    return graph


def _move_nodes(graph, resolution, rng):
    """One Louvain level: move single nodes to the neighbouring community with the best
    modularity gain until nothing moves. Returns (community per node, anything moved)."""
    degree = np.array([sum(links.values()) for links in graph], dtype=float)
    total = degree.sum() or 1.0
    community = list(range(len(graph)))
    community_degree = degree.copy()
    improved, moved = False, True
    order = rng.permutation(len(graph)).tolist()
    while moved:
        moved = False
        for node in order:
            current = community[node]
            links = {}
            for other, weight in graph[node].items():
                if other != node:
                    links[community[other]] = links.get(community[other], 0) + weight
            community_degree[current] -= degree[node]
            share = resolution * degree[node] / total
            best, best_gain = current, links.get(current, 0) - share * community_degree[current]
            for candidate, weight in links.items():
                gain = weight - share * community_degree[candidate]
                if gain > best_gain + 1e-12:
                    best, best_gain = candidate, gain
            community_degree[best] += degree[node]
            if best != current:
                community[node] = best
                moved = improved = True
    return community, improved


def louvain(graph, resolution=1.0, seed=0):
    """Communities of a symmetric weighted graph (list of {node: weight}), Louvain method."""
    rng = np.random.default_rng(seed)
    membership = np.arange(len(graph))
    while True:
        community, improved = _move_nodes(graph, resolution, rng)
        if not improved:
            return membership
        ids = {old: new for new, old in enumerate(sorted(set(community)))}
        community = np.array([ids[c] for c in community])
        membership = community[membership]
        aggregated = [dict() for _ in ids]       # one node per community, internal links as a self-loop
        for node, links in enumerate(graph):
            source = community[node]
            for other, weight in links.items():
                target = community[other]
                aggregated[source][target] = aggregated[source].get(target, 0) + weight
        graph = aggregated


def density_groups(points, dense_share=0.4, min_samples=DENSE_NEIGHBOURS, chunk=1024):
    """DBSCAN on 2D points; the radius is chosen so that dense_share of the points are core
    points. Border points join the group of their nearest core point; the rest get -1."""
    points = np.asarray(points, np.float64)
    n = len(points)
    labels = np.full(n, -1)
    if n <= min_samples:
        return labels

    def distances(start):
        block = points[start:start + chunk]
        return np.sqrt(((block[:, None, :] - points[None, :, :]) ** 2).sum(-1))

    kth = np.concatenate([np.partition(distances(start), min_samples, axis=1)[:, min_samples]
                          for start in range(0, n, chunk)])   # column 0 is the point itself
    radius = np.quantile(kth, dense_share)
    core = kth <= radius
    parent = np.arange(n)

    def root(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    nearest_core = np.full(n, -1)
    for start in range(0, n, chunk):
        block = distances(start)
        near = block <= radius
        for offset in np.nonzero(core[start:start + chunk])[0]:
            node = start + offset
            for other in np.nonzero(near[offset] & core)[0]:
                a, b = root(node), root(other)
                if a != b:
                    parent[a] = b
        to_core = np.where(near & core[None, :], block, np.inf)
        closest = np.argmin(to_core, axis=1)
        reachable = np.isfinite(to_core[np.arange(len(block)), closest])
        nearest_core[start:start + chunk] = np.where(reachable, closest, -1)
    for node in range(n):
        if core[node]:
            labels[node] = root(node)
        elif nearest_core[node] >= 0:
            labels[node] = root(nearest_core[node])
    # Tiny clumps (on the real library: dozens of 8-15 track groups) are noise, not groups.
    values, counts = np.unique(labels[labels >= 0], return_counts=True)
    small = values[counts < max(2 * min_samples, n // 100)]
    labels[np.isin(labels, small)] = -1
    return labels


def _by_size(labels):
    """Renumber groups so 0 is the largest; -1 (ungrouped) stays -1."""
    labels = np.asarray(labels)
    grouped = labels[labels >= 0]
    if not len(grouped):
        return labels.copy()
    values, counts = np.unique(grouped, return_counts=True)
    order = values[np.argsort(-counts, kind='stable')]
    mapping = {value: index for index, value in enumerate(order.tolist())}
    return np.array([mapping.get(label, -1) for label in labels.tolist()])


def group_tracks(method, vectors, points, parameter, should_stop=lambda: False):
    """Group per track (array aligned with vectors and points); -1 = no group. Slow for
    thousands of tracks (seconds): run in a thread."""
    if len(vectors) == 0:
        return np.zeros(0, int)
    if method == 'kmeans':
        labels = kmeans(vectors, int(parameter))
    elif method == 'communities':
        graph = knn_graph(vectors)
        if should_stop():
            return None
        labels = louvain(graph, float(parameter))
    elif method == 'density':
        labels = density_groups(points, float(parameter) / 100)
    else:
        raise ValueError(f'unknown grouping method: {method}')
    return _by_size(labels)

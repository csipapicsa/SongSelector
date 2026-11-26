"""How stable is the teacher's own top-10 when it hears other windows of the same songs?

Validation tracks have 16 cached windows each. For tracks with at least 12, draw 6 windows at random and 6 others,
build a track vector from each set (as the app does: mean of unit window vectors, unit length), and compare the
two top-10 neighbour lists (top_k_overlap, as for the students). Also 6 windows against all 16. Five draws.

The student's top-10 overlap is measured against the teacher on the *same* windows; this gives a scale for it: how
much the teacher's own list moves when only the sampled moments of each song change.

    .research_cache\\venv-distill\\Scripts\\python research\\experiments\\distill\\teacher_stability.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate import top_k_overlap  # noqa: E402
from train import load_data, track_vectors  # noqa: E402


def main(draws=5):
    val = load_data(None, 0)['val']
    tracks, teacher = val['tracks'], val['teacher']
    ids, counts = np.unique(tracks, return_counts=True)
    keep = ids[counts >= 12]   # two disjoint sets of 6; a few tracks are shorter (every row must line up)
    print(f'{len(keep)} of {len(ids)} validation tracks have at least 12 windows')
    results = {'6 windows vs 6 other windows': [], '6 windows vs all 16 (incl. those 6)': []}
    for seed in range(draws):
        rng = np.random.default_rng(seed)
        a_rows, b_rows, all_rows = [], [], []
        for track in keep:
            rows = np.flatnonzero(tracks == track)
            drawn = rng.permutation(rows)
            a_rows += list(drawn[:6])
            b_rows += list(drawn[6:12])
            all_rows += list(rows)
        vectors = []
        for rows in (a_rows, b_rows, all_rows):
            rows = np.sort(rows)
            vectors.append(track_vectors(teacher[rows], tracks[rows]))
        (a, a_ids), (b, b_ids), (every, every_ids) = vectors
        assert np.array_equal(a_ids, b_ids) and np.array_equal(a_ids, every_ids)
        results['6 windows vs 6 other windows'].append(top_k_overlap(a, b))
        results['6 windows vs all 16 (incl. those 6)'].append(top_k_overlap(a, every))
    for name, values in results.items():
        print(f'teacher, {name}: top-10 overlap {np.mean(values):.3f} ({draws} draws, {min(values):.3f}-{max(values):.3f})')


if __name__ == '__main__':
    main()

# %% [markdown]
# # Rating and colour: how well does an embedding predict them?
# Protocol: docs/research/rating_color_plan.md. Run: `python evaluate.py --model cnn14`
# (VS Code opens the `# %%` cells like a notebook.) Every model goes through the same probes and
# the same artist-grouped, repeated cross-validation, and is compared with "always the most common value".

# %%
import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
from sklearn.metrics import balanced_accuracy_score, f1_score, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (CACHE, REPO, bootstrap, cross_validated, fmt, load_labels, load_vectors, locked_test,
                    precision_at_coverage, probe_scores, restrict, snapshot_data)

warnings.filterwarnings('ignore')
parser = argparse.ArgumentParser()
parser.add_argument('--model', default='cnn14', help='cnn14, or a model with .research_cache/vectors/<model>.npz')
parser.add_argument('--app-data', default=str(REPO / 'dist'), help="folder of the app's library.sqlite / embeddings.sqlite")
parser.add_argument('--keys-of', default='', help='only the tracks another model has vectors for (same tracks for a fair comparison)')
parser.add_argument('--refresh', action='store_true', help='copy the app data again')
parser.add_argument('--probes', default='majority,knn,logistic')
parser.add_argument('--final', action='store_true',
                    help='ONCE, for the chosen setup: train on the development artists, test on the locked 20 %%')
args = parser.parse_args() if sys.argv[0].endswith('evaluate.py') else parser.parse_args([])

# %% [markdown]
# ## Data: one vector per track, labels, artist groups

# %%
snapshot = snapshot_data(args.app_data, args.refresh)
vectors = load_vectors(args.model, snapshot)
if args.keys_of:
    vectors = restrict(vectors, load_vectors(args.keys_of, snapshot).keys)
rating, colour, groups = load_labels(snapshot, vectors.keys)
locked = locked_test(groups)
print(f'{args.model}: {len(vectors.keys)} tracks, {vectors.matrix.shape[1]} values each; '
      f'{(rating > 0).sum()} rated, {(colour > 0).sum()} coloured (1-7)')

# %% [markdown]
# ## Targets
# * `rating` 1-5, `rating 4-5` (high vs not), `colour` 1-7 and each colour against the rest.
# * Colour 0 means "no colour" in Traktor and is left out, like unrated tracks.

# %%
MIN_POSITIVES = 60
results = {'model': args.model, 'tracks': len(vectors.keys), 'date': time.strftime('%Y-%m-%d'), 'targets': {}}


def run(target, mask, y, probes, ordinal=False, one_vs_rest=()):
    if args.final:
        run_final(target, mask, y, probes)
        return
    mask = mask & ~locked  # choices are made on the development artists only
    x, y, g = vectors.matrix[mask], y[mask], groups[mask]
    print(f'\n{target}: {len(y)} labelled tracks, {len(np.unique(g))} artist groups')
    out = results['targets'][target] = {'n': int(len(y))}
    for probe in probes:
        proba, classes = cross_validated(probe, x, y, g)
        pred = classes[proba.argmax(1)]
        balanced = bootstrap(balanced_accuracy_score, y, pred)
        macro = bootstrap(lambda a, b: f1_score(a, b, average='macro'), y, pred)
        line = f'  {probe:9s} balanced accuracy {fmt(*balanced)}, macro-F1 {fmt(*macro)}'
        entry = {'balanced_accuracy': balanced, 'macro_f1': macro}
        if ordinal:
            mae = bootstrap(lambda a, b: np.mean(abs(a - b)), y, pred)
            near = bootstrap(lambda a, b: np.mean(abs(a - b) <= 1), y, pred)
            line += f', within 1 star {fmt(*near)}, mean error {fmt(*mae, percent=False)} stars'
            entry.update(mae=mae, within1=near)
        print(line)
        out[probe] = entry
        for name, positive in one_vs_rest:
            truth = (y == positive).astype(int)
            score = proba[:, list(classes).index(positive)]
            if truth.sum() < MIN_POSITIVES:
                continue
            auc = bootstrap(roc_auc_score, truth, score)
            precision = precision_at_coverage(truth, score, 0.2)
            print(f'      {name:12s} AUC {fmt(*auc, percent=False)}  (share of tracks {truth.mean():.0%}, '
                  f'top 20 % by score are right {precision:.0%})')
            entry[name] = {'auc': auc, 'share': float(truth.mean()), 'precision_top20': precision}


def run_final(target, mask, y, probes):
    """The one look at the locked artists: fit on the development artists, score the locked ones."""
    train, test = mask & ~locked, mask & locked
    print(f'\n{target} (FINAL, locked artists): train {train.sum()}, test {test.sum()}')
    for probe in probes:
        proba, classes = probe_scores(probe, vectors.matrix[train], y[train], vectors.matrix[test])
        pred = classes[proba.argmax(1)]
        print(f'  {probe:9s} balanced accuracy {fmt(*bootstrap(balanced_accuracy_score, y[test], pred))}')
        for c in classes:
            truth = (y[test] == c).astype(int)
            if truth.sum() >= 20:
                print(f'      class {c}: AUC {fmt(*bootstrap(roc_auc_score, truth, proba[:, list(classes).index(c)]), percent=False)}, '
                      f'top 20 % by score are right {precision_at_coverage(truth, proba[:, list(classes).index(c)], 0.2):.0%}'
                      f' (share {truth.mean():.0%})')


probes = args.probes.split(',')
run('rating (1-5)', rating > 0, rating, probes, ordinal=True, one_vs_rest=[(f'{s} stars', s) for s in (1, 2, 3, 4, 5)])
run('colour (1-7)', colour > 0, colour, probes, one_vs_rest=[(f'colour {c}', c) for c in range(1, 8)])
high = np.where(rating >= 4, 2, 1)
run('rating high (4-5 vs 1-3)', rating > 0, high, probes, one_vs_rest=[('4-5 stars', 2)])

# %% [markdown]
# ## Save: one JSON per run, kept in git (small)

# %%
if not args.final:
    target = REPO / 'docs' / 'research' / 'experiments' / 'results' / f"{results['date']}_{args.model}{'_on-' + args.keys_of if args.keys_of else ''}.json"
    target.write_text(json.dumps(results, indent=1, default=float), encoding='utf-8')
    print('\nsaved', target.relative_to(REPO))

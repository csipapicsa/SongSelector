# %% [markdown]
# # Do alike tracks end up together? (a check that a model's vectors mean something)
# For tracks whose genre tag names exactly one of dnb / breaks / house / downtempo: the share of each
# track's 10 nearest tracks (cosine) with the same style. Chance = the share of that style. The same
# check was used for CNN14 in docs/research/audio_embeddings.md. Run: `python neighbours.py cnn14 musicnn ...`
# All models are compared on the tracks they all have.

# %%
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO, load_vectors, restrict, snapshot_data

STYLES = {'dnb': r'drum|dnb|d\&b|jungle|neurofunk|liquid', 'breaks': r'break', 'house': r'house', 'downtempo': r'down\s*tempo|chill'}

# %%
names = sys.argv[1:] or ['cnn14']
snapshot = snapshot_data(REPO / 'dist')
vectors = {name: load_vectors(name, snapshot) for name in names}
common = set.intersection(*(set(v.keys) for v in vectors.values()))
vectors = {name: restrict(v, common) for name, v in vectors.items()}
genres = dict(sqlite3.connect(snapshot / 'library.sqlite').execute('SELECT path_key, genre FROM tracks'))


def style_of(text):
    found = [style for style, pattern in STYLES.items() if re.search(pattern, (text or '').lower())]
    return found[0] if len(found) == 1 else None


print(f'{len(common)} tracks in common')
for name, v in vectors.items():
    styles = np.array([style_of(genres.get(key)) or '' for key in v.keys])
    keep = np.where(styles != '')[0]
    scores = v.matrix[keep] @ v.matrix[keep].T
    np.fill_diagonal(scores, -9)
    top = np.argsort(-scores, axis=1)[:, :10]
    same = (styles[keep][top] == styles[keep][:, None]).mean()
    chance = sum((styles[keep] == s).mean() ** 2 for s in set(styles[keep]))
    per_style = {s: round(float((styles[keep][top][styles[keep] == s] == s).mean()), 2) for s in sorted(set(styles[keep]))}
    print(f'{name:15s} {same:.0%} of the 10 nearest share the style (chance {chance:.0%}), {len(keep)} tracks; per style {per_style}')

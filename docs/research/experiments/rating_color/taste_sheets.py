# %% [markdown]
# # Sheets for your own judgement (CSV, opens in Excel)
# Two kinds, each with a "make" and a "score" step:
#
# * `rerate-make` / `rerate-score`: a blind sheet of ~60 tracks you rated before. You rate them again
#   without seeing the old values; the agreement with yourself is the ceiling for any model.
# * `valid-make` / `valid-score`: the model's rating and colour suggestions for tracks that have none.
#   You mark each with yes / no ("does this match my taste?"); the score is the share of yes.
#
# Run from this folder: `python taste_sheets.py rerate-make`, etc. Files go to docs/research/sheets/.
# CSV: UTF-8 with BOM, semicolon-separated (what a Hungarian-locale Excel opens as columns);
# reading accepts comma or semicolon.

# %%
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CACHE, REPO, load_labels, load_vectors, snapshot_data

SHEETS = REPO / 'docs' / 'research' / 'sheets'
RESULTS = REPO / 'docs' / 'research' / 'experiments' / 'results'
COLOUR_NAMES = {1: 'red', 2: 'orange', 3: 'yellow', 4: 'green', 5: 'blue', 6: 'indigo', 7: 'violet'}
COLOUR_NUMBER = {name: number for number, name in COLOUR_NAMES.items()}
DATE = time.strftime('%Y-%m-%d')


def write_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, columns, delimiter=';', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    text = Path(path).read_text(encoding='utf-8-sig')
    delimiter = ';' if text.splitlines()[0].count(';') >= text.splitlines()[0].count(',') else ','
    return list(csv.DictReader(text.splitlines(), delimiter=delimiter))


def track_table(snapshot):
    """{path_key: dict} of the library's tags, rating and colour (None where unset)."""
    import sqlite3
    rows = sqlite3.connect(snapshot / 'library.sqlite').execute(
        'SELECT path_key, artist, title, genre, bpm, file_path, rating, color FROM tracks')
    return {key: dict(Artist=artist or '', Title=title or '', Genre=genre or '', BPM=round(bpm) if bpm else '',
                      Path=path, rating=int(rating) if rating else 0, colour=int(colour) if colour else 0)
            for key, artist, title, genre, bpm, path, rating, colour in rows}


def colour_value(text):
    text = (text or '').strip().lower()
    if text.isdigit():
        return int(text)
    return COLOUR_NUMBER.get(text, 0)


# %% [markdown]
# ## Re-rating: a blind sheet

# %%
def rerate_make(snapshot, count=60, seed=0):
    import os
    table = track_table(snapshot)
    pool = [(k, t) for k, t in table.items() if t['rating'] > 0 and 1 <= t['colour'] <= 7 and os.path.exists(t['Path'])]
    rng = np.random.default_rng(seed)
    per_star = count // 5
    chosen = []
    for star in range(1, 6):  # the same number of tracks per rating, so rare ratings are tested too
        group = [item for item in pool if item[1]['rating'] == star]
        rng.shuffle(group)
        chosen += group[:per_star]
    rng.shuffle(chosen)
    rows = [dict(n=i + 1, **{c: t[c] for c in ('Artist', 'Title', 'BPM', 'Path')}, new_rating='', new_colour='')  # no genre: its notes (e:4) could cue
            for i, (key, t) in enumerate(chosen)]
    target = SHEETS / f'rerate_{DATE}.csv'
    write_csv(target, rows, ['n', 'Artist', 'Title', 'BPM', 'Path', 'new_rating', 'new_colour'])
    # which track is which is found again by its Path; the old values are not in the sheet (blind)
    print(f'{len(rows)} tracks -> {target.relative_to(REPO)}')
    print('Fill new_rating (1-5) and new_colour (1-7 or red/orange/yellow/green/blue/indigo/violet) from your '
          'feeling now, without looking at Traktor. Leave a row empty to skip it.')


def rerate_score(snapshot, path):
    from sklearn.metrics import cohen_kappa_score
    table = {t['Path']: t for t in track_table(snapshot).values()}
    pairs = []
    for row in read_csv(path):
        old = table.get(row['Path'])
        new_rating = int(row['new_rating']) if (row.get('new_rating') or '').strip().isdigit() else 0
        if old and new_rating:
            pairs.append((old['rating'], new_rating, old['colour'], colour_value(row.get('new_colour'))))
    if not pairs:
        print('No filled rows yet.')
        return
    a = np.array(pairs)
    out = {'date': DATE, 'rated_again': int(len(a))}
    out['rating_exact'] = float(np.mean(a[:, 0] == a[:, 1]))
    out['rating_within1'] = float(np.mean(abs(a[:, 0] - a[:, 1]) <= 1))
    out['rating_mean_error'] = float(np.mean(abs(a[:, 0] - a[:, 1])))
    out['rating_weighted_kappa'] = float(cohen_kappa_score(a[:, 0], a[:, 1], weights='quadratic'))
    coloured = a[:, 3] > 0
    if coloured.sum():
        out['colour_rows'] = int(coloured.sum())
        out['colour_exact'] = float(np.mean(a[coloured, 2] == a[coloured, 3]))
        out['colour_kappa'] = float(cohen_kappa_score(a[coloured, 2], a[coloured, 3]))
    print(json.dumps(out, indent=1))
    print('\nHow to read: this is you against yourself. A model cannot be expected to beat these numbers.\n'
          'Rating: kappa > 0.8 very consistent, 0.6-0.8 good, 0.4-0.6 moderate, < 0.4 weak. Compare with the '
          'models in rating_color_prediction.md.')
    (RESULTS / f'{DATE}_rerate.json').write_text(json.dumps(out, indent=1), encoding='utf-8')


# %% [markdown]
# ## Valid: does the suggestion match your taste?

# %%
def valid_make(snapshot, model, per_kind=40, seed=0):
    import os
    from sklearn.decomposition import PCA
    from sklearn.linear_model import LogisticRegression
    vectors = load_vectors(model, snapshot)
    table = track_table(snapshot)
    rating, colour, _ = load_labels(snapshot, vectors.keys)
    x = vectors.matrix
    preds = {}
    for name, labels, valid in (('rating', rating, rating > 0), ('colour', colour, (colour >= 1) & (colour <= 7))):
        pca = PCA(100, random_state=0).fit(x[valid])
        clf = LogisticRegression(C=0.3, max_iter=3000).fit(pca.transform(x[valid]), labels[valid])
        proba = clf.predict_proba(pca.transform(x))
        preds[name] = (clf.classes_[proba.argmax(1)], proba.max(1), valid)
    exists = np.array([os.path.exists(table[k]['Path']) for k in vectors.keys])
    missing = {name: ~preds[name][2] & exists for name in preds}
    rng = np.random.default_rng(seed)
    chosen = {}  # row index -> chosen_by
    for name in ('rating', 'colour'):
        candidates = np.where(missing[name])[0]
        surest = candidates[np.argsort(-preds[name][1][candidates])[:per_kind]]
        for i in surest:
            chosen.setdefault(int(i), f'surest {name}')
    union = np.where(missing['rating'] | missing['colour'])[0]
    for i in rng.choice(union, per_kind, replace=False):
        chosen.setdefault(int(i), 'random')
    labelled_x = x[(rating > 0) | (colour > 0)]
    labelled_rows = np.where((rating > 0) | (colour > 0))[0]
    rows = []
    for i, by in sorted(chosen.items(), key=lambda kv: kv[1]):
        t = table[vectors.keys[i]]
        near = labelled_rows[np.argsort(-(labelled_x @ x[i]))[:5]]
        row = dict(Artist=t['Artist'], Title=t['Title'], Genre=t['Genre'], BPM=t['BPM'], Path=t['Path'], chosen_by=by,
                   similar_ratings=','.join(str(rating[j]) for j in near if rating[j] > 0),
                   similar_colours=','.join(COLOUR_NAMES.get(colour[j], '') for j in near if 1 <= colour[j] <= 7))
        if missing['rating'][i]:
            row.update(predicted_rating=int(preds['rating'][0][i]), rating_confidence=f"{preds['rating'][1][i]:.0%}")
        if missing['colour'][i]:
            row.update(predicted_colour=COLOUR_NAMES[int(preds['colour'][0][i])],
                       colour_confidence=f"{preds['colour'][1][i]:.0%}")
        row.update(valid_rating='', valid_colour='')
        rows.append(row)
    target = SHEETS / f'valid_{model}_{DATE}.csv'
    write_csv(target, rows, ['Artist', 'Title', 'Genre', 'BPM', 'Path', 'chosen_by', 'predicted_rating', 'rating_confidence',
                             'valid_rating', 'predicted_colour', 'colour_confidence', 'valid_colour', 'similar_ratings',
                             'similar_colours'])
    print(f'{len(rows)} tracks -> {target.relative_to(REPO)}')
    print('Mark valid_rating / valid_colour with yes or no: "does this suggestion match what I would have set?" '
          'Only where there is a prediction. Leave the rest empty.')


def valid_score(path):
    rows = read_csv(path)
    out = {'date': DATE, 'file': Path(path).name}
    for kind in ('rating', 'colour'):
        answered = [(r, (r.get(f'valid_{kind}') or '').strip().lower()) for r in rows if (r.get(f'valid_{kind}') or '').strip()]
        yes = [r for r, a in answered if a.startswith(('y', 'i'))]  # yes / igen
        if not answered:
            continue
        out[kind] = {'answered': len(answered), 'yes': len(yes), 'share_yes': len(yes) / len(answered)}
        for by in sorted({r['chosen_by'] for r, _ in answered}):
            group = [(r, a) for r, a in answered if r['chosen_by'] == by]
            out[kind][by] = f"{sum(a.startswith(('y', 'i')) for _, a in group)}/{len(group)}"
        by_value = {}
        for r, a in answered:
            by_value.setdefault(r[f'predicted_{kind}'], []).append(a.startswith(('y', 'i')))
        out[kind]['by_predicted_value'] = {k: f'{sum(v)}/{len(v)}' for k, v in sorted(by_value.items())}
    print(json.dumps(out, indent=1))
    (RESULTS / f'{DATE}_valid_{Path(path).stem}.json').write_text(json.dumps(out, indent=1), encoding='utf-8')


# %%
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['rerate-make', 'rerate-score', 'valid-make', 'valid-score'])
    parser.add_argument('file', nargs='?', help='the filled sheet (for the score commands)')
    parser.add_argument('--model', default='cnn14')
    parser.add_argument('--app-data', default=str(REPO / 'dist'))
    args = parser.parse_args()
    snapshot = snapshot_data(args.app_data)
    if args.command == 'rerate-make':
        rerate_make(snapshot)
    elif args.command == 'rerate-score':
        rerate_score(snapshot, args.file)
    elif args.command == 'valid-make':
        valid_make(snapshot, args.model)
    else:
        valid_score(args.file)

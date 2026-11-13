# %% [markdown]
# # Does anything besides the sound predict rating and colour?
# Traktor's collection.nml holds how a track was *used*: play count, last played, import date, number of
# hot cues and cues, number of playlists it is on, loudness, bitrate, length, BPM, key. Tested alone and
# together with the CNN14 sound vectors, with the same artist-grouped validation as `evaluate.py`.
# Run: `python metadata.py`  (copies collection.nml into .research_cache/snapshot first)

# %%
import shutil
import sys
import warnings
from collections import Counter
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
from sklearn.decomposition import PCA
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import balanced_accuracy_score, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO, bootstrap, fmt, fold_splits, load_labels, load_vectors, locked_test, snapshot_data
from songselector.core.traktor_collection import canonical_path, nml_track_path

warnings.filterwarnings('ignore')
NML = Path(r'E:\DJ\TRAKTOR\collection.nml')


def days(text, today):
    """Days between a Traktor date 'YYYY/M/D' and `today`; NaN if unset."""
    try:
        year, month, day = (int(part) for part in text.split('/'))
        return (today - date(year, month, day)).days
    except (AttributeError, ValueError):
        return np.nan


# %% [markdown]
# ## Parse the collection: one row of numbers per track

# %%
FEATURES = ['bpm', 'bpm_quality', 'key', 'playcount', 'days_since_played', 'days_since_import', 'bitrate_kbps',
            'minutes', 'filesize_mb', 'perceived_db', 'peak_db', 'analyzed_db', 'hotcues', 'cues', 'playlists']


def parse_collection(snapshot):
    target = snapshot / 'collection.nml'
    if not target.exists():
        shutil.copy2(NML, target)
    today = date.fromtimestamp(target.stat().st_mtime)
    rows, membership, nodes = {}, Counter(), 0
    for event, entry in ET.iterparse(target, events=('end',)):
        if entry.tag != 'ENTRY':
            continue
        location = entry.find('LOCATION')
        if location is None:  # a playlist entry
            key = entry.find('PRIMARYKEY')
            if key is not None:
                membership[canonical_path(nml_track_path(key.get('KEY')))] += 1
            continue
        directory = location.get('DIR', '').replace('/:', '/').replace('/', '\\')
        volume = location.get('VOLUME', '')
        path = canonical_path((volume + ':' if len(volume) == 1 else volume) + directory + location.get('FILE', ''))
        info, tempo, key = entry.find('INFO'), entry.find('TEMPO'), entry.find('MUSICAL_KEY')
        info = info.attrib if info is not None else {}
        loud = entry.find('LOUDNESS')
        loud = loud.attrib if loud is not None else {}
        cues = entry.findall('CUE_V2')
        number = lambda value: float(value) if value not in (None, '') else np.nan
        rows[path] = dict(
            bpm=number(tempo.get('BPM')) if tempo is not None else np.nan,
            bpm_quality=number(tempo.get('BPM_QUALITY')) if tempo is not None else np.nan,
            key=number(key.get('VALUE')) if key is not None else np.nan,
            playcount=number(info.get('PLAYCOUNT')),
            days_since_played=days(info.get('LAST_PLAYED'), today), days_since_import=days(info.get('IMPORT_DATE'), today),
            bitrate_kbps=number(info.get('BITRATE')) / 1000, minutes=number(info.get('PLAYTIME_FLOAT')) / 60,
            filesize_mb=number(info.get('FILESIZE')) / 1000,
            perceived_db=number(loud.get('PERCEIVED_DB')), peak_db=number(loud.get('PEAK_DB')),
            analyzed_db=number(loud.get('ANALYZED_DB')),
            hotcues=sum(c.get('HOTCUE', '-1') not in ('-1', '') and c.get('TYPE') == '0' for c in cues),
            cues=len(cues))
        entry.clear()
    for path, row in rows.items():
        row['playlists'] = membership.get(path, 0)
    return rows


# %%
snapshot = snapshot_data(REPO / 'dist')
nml = parse_collection(snapshot)
vectors = load_vectors('cnn14', snapshot)
rating, colour, groups = load_labels(snapshot, vectors.keys)
meta = np.array([[nml.get(key, {}).get(name, np.nan) for name in FEATURES] for key in vectors.keys], np.float32)
found = np.array([key in nml for key in vectors.keys])
print(f'{found.sum()} of {len(found)} tracks found in the collection; {len(nml)} collection entries')
locked = locked_test(groups)

# %% [markdown]
# ## Are the unlabelled tracks like the labelled ones? (a model is only useful if they are)

# %%
labelled = (rating > 0) | ((colour >= 1) & (colour <= 7))
for name in ('playcount', 'hotcues', 'playlists', 'days_since_import', 'bitrate_kbps'):
    column = FEATURES.index(name)
    a, b = meta[labelled, column], meta[~labelled & found, column]
    print(f'  {name:18s} labelled: median {np.nanmedian(a):7.1f}, share > 0 {np.nanmean(a > 0):4.0%} | '
          f'unlabelled: median {np.nanmedian(b):7.1f}, share > 0 {np.nanmean(b > 0):4.0%}')

# %% [markdown]
# ## Probes
# * metadata only: gradient boosting (handles missing values)
# * sound only: logistic regression on PCA-100 of CNN14 (as in evaluate.py)
# * both: gradient boosting on the metadata plus the first 20 PCA components of the sound

# %%
def predict(kind, x_train, m_train, y_train, x_test, m_test):
    classes = np.unique(y_train)
    if kind == 'sound':
        from sklearn.linear_model import LogisticRegression
        pca = PCA(100, random_state=0).fit(x_train)
        model = LogisticRegression(C=0.3, max_iter=3000).fit(pca.transform(x_train), y_train)
        return model.predict_proba(pca.transform(x_test)), model.classes_
    if kind == 'meta':
        a, b = m_train, m_test
    else:
        pca = PCA(20, random_state=0).fit(x_train)
        a, b = np.hstack([m_train, pca.transform(x_train)]), np.hstack([m_test, pca.transform(x_test)])
    model = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150, l2_regularization=1.0,
                                           random_state=0).fit(a, y_train)
    return model.predict_proba(b), model.classes_


def evaluate(target, y, wanted, kinds=('meta', 'sound', 'both'), drop=()):
    use = [i for i, name in enumerate(FEATURES) if name not in drop]
    mask = wanted & found & ~locked
    x, m, y, g = vectors.matrix[mask], meta[mask][:, use], y[mask], groups[mask]
    classes = np.unique(y)
    print(f'\n{target}: {mask.sum()} tracks' + (f' (without {", ".join(drop)})' if drop else ''))
    for kind in kinds:
        total, count = np.zeros((len(y), len(classes))), np.zeros(len(y))
        for train, test in fold_splits(y, g, 5, 2):
            proba, seen = predict(kind, x[train], m[train], y[train], x[test], m[test])
            total[np.ix_(test, np.searchsorted(classes, seen))] += proba
            count[test] += 1
        proba = total / count[:, None]
        pred = classes[proba.argmax(1)]
        line = f'  {kind:6s} balanced accuracy {fmt(*bootstrap(balanced_accuracy_score, y, pred))}'
        for c in classes:
            truth = (y == c).astype(int)
            if truth.sum() >= 60:
                line += f' | {c}: AUC {bootstrap(roc_auc_score, truth, proba[:, list(classes).index(c)])[0]:.2f}'
        print(line)


high = np.where(rating >= 4, 2, 1)
evaluate('rating 4-5 vs 1-3', high, rating > 0)
evaluate('rating 1-5', rating, rating > 0)
evaluate('colour 1-7', colour, (colour >= 1) & (colour <= 7))

# %% [markdown]
# ## Which features carry it? Leave out the "usage" ones: play count, last played, hot cues, cues, playlists.
# Those exist only because the track was played and worked on; for a new, unplayed track they are zero,
# so a model leaning on them cannot help exactly where it is needed.

# %%
usage = ('playcount', 'days_since_played', 'hotcues', 'cues', 'playlists')
evaluate('rating 4-5 vs 1-3, no usage features', high, rating > 0, kinds=('meta', 'both'), drop=usage)
evaluate('colour 1-7, no usage features', colour, (colour >= 1) & (colour <= 7), kinds=('meta', 'both'), drop=usage)

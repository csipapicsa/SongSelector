# %% [markdown]
# # Are the front ends right?
# `python selfcheck.py --prepare` (system Python, needs librosa) makes the mel filter matrices once.
# `python selfcheck.py` compares the numpy spectrograms with librosa and prints the models' own tag
# outputs for tracks with a known genre: a wrong front end shows up as nonsense tags.

# %%
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import models
from common import CACHE, REPO

parser = argparse.ArgumentParser()
parser.add_argument('--prepare', action='store_true')
parser.add_argument('--tracks', type=int, default=3, help='tracks per genre for the tag check')
args = parser.parse_args()

# %% [markdown]
# ## Mel filter matrices (once, with librosa)

# %%
if args.prepare:
    import librosa
    models.MODELS.mkdir(parents=True, exist_ok=True)
    # musicnn: librosa defaults (Slaney scale, area normalisation), 96 bands up to 8 kHz
    np.save(models.MODELS / 'mel_musicnn.npy', librosa.filters.mel(sr=16000, n_fft=512, n_mels=96).astype(np.float32))
    # openl3 (kapre): HTK scale, 128 bands up to 24 kHz
    np.save(models.MODELS / 'mel_openl3.npy',
            librosa.filters.mel(sr=48000, n_fft=2048, n_mels=128, fmin=0, fmax=24000, htk=True).astype(np.float32))
    print('saved mel filters to', models.MODELS)
    sys.exit()

# %% [markdown]
# ## 1. The numpy spectrogram equals librosa's

# %%
try:
    import librosa
    rng = np.random.default_rng(0)
    signal = rng.normal(0, 0.1, 16000 * 3).astype(np.float32)
    mine = models.musicnn_mel(signal)
    theirs = np.log10(10000.0 * librosa.feature.melspectrogram(y=signal, sr=16000, n_fft=512, hop_length=256, n_mels=96).T + 1.0)
    print(f'musicnn mel: {mine.shape} vs librosa {theirs.shape}, max difference {np.abs(mine - theirs).max():.2e}')
except ImportError:
    print('librosa not installed in this Python: skipped')

# %% [markdown]
# ## 2. What the models say about tracks of a known genre
# Genre from the library's own tags (dnb / house / breakbeat / downtempo ...). MusiCNN gives 50 MSD tags,
# Discogs-EffNet 400 Discogs styles. Expect electronic / dance / house / drum n bass terms, not "country".

# %%
tags = {'musicnn': json.loads((models.MODELS / 'msd-musicnn-1.json').read_text())['classes'],
        'discogs_effnet': json.loads((models.MODELS / 'discogs-effnet-bs64-1.json').read_text())['classes']}
snapshot = CACHE / 'snapshot'
connection = sqlite3.connect(snapshot / 'library.sqlite')
rows = connection.execute('SELECT file_path, genre FROM tracks').fetchall()
wanted = {'dnb': 'drum', 'house': 'house', 'breakbeat': 'breakbeat', 'downtempo': 'downtempo'}
by_genre = {}
for path, genre in rows:
    text = (genre or '').lower()
    for label, needle in wanted.items():
        if needle in text and Path(path).exists() and len(by_genre.setdefault(label, [])) < args.tracks:
            by_genre[label].append(path)

for cls in (models.MusiCNN, models.DiscogsEffNet):
    model = cls()
    names = tags[model.name]
    print(f'\n{model.name} (on {model.session.get_providers()[0]})')
    for label, paths in by_genre.items():
        for path in paths:
            audio = models.decode(path, [16000])
            embeddings, activations = model.windows(audio, with_tags=True)
            mean = activations.mean(0)
            top = [names[i] if names else i for i in np.argsort(-mean)[:4]]
            print(f'  {label:10s} {Path(path).name[:42]:42s} {embeddings.shape} top: {", ".join(map(str, top))}')

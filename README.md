# SongSelector

[![CI](https://github.com/csipapicsa/SongSelector/actions/workflows/ci.yml/badge.svg)](https://github.com/csipapicsa/SongSelector/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/csipapicsa/SongSelector)](https://github.com/csipapicsa/SongSelector/releases/latest)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue)
![Windows](https://img.shields.io/badge/platform-Windows-lightgrey)

A Windows desktop app that helps DJs pick the next track. It sits next to Traktor or Rekordbox, reads
their libraries automatically, and answers two questions:

- **Will it mix in key at the tempo I'm playing?** With Key Lock off, speeding a track up raises its
  pitch. SongSelector shows every track's key *at the current master tempo*, in Musical, Camelot and
  Open Key notation, and recalculates the whole library as you move the tempo slider.
- **What sounds like this track?** A neural audio model (PANNs CNN14, run through ONNX Runtime on
  the GPU) turns every track into embeddings in the background. A similarity map and a
  closest-matches list then show tracks that *sound* alike, whatever their tags say.

## Features

**Harmonic mixing**
- Tempo-adjusted key for every track: `semitones = round(12 · log2(target / original BPM))`
- Harmonic partners on the Camelot wheel (perfect, ±1, scale change, energy boost and four more mix
  types) as edges on the map and as a filter for the closest matches

**Audio similarity**
- CNN14 embeddings (2048 values per 5 s of audio) for the whole library, in a low-priority background
  process; on the GPU through DirectML (any DirectX 12 card), otherwise on the CPU
- Similarity map (t-SNE, 2D or 3D, implemented in numpy to keep scikit-learn out of the exe) with
  closest matches, drag and drop into Traktor's decks
- Unsupervised groups (k-means, neighbour communities, map density) as a sortable List column
- On the developer's library the map separated breakbeat and drum & bass with about 93 % purity,
  from audio alone

**Library integration, without export steps**
- Traktor: reads `collection.nml` (key, BPM, colour, rating, playlists) and re-reads it when
  Traktor saves; never writes to it
- Rekordbox: reads playlists directly from its encrypted `master.db` (from a temporary copy);
  nothing to export, Rekordbox does not have to be closed
- Drag and drop MP3, WAV and FLAC files or whole folders; reads their tags, writes edited
  Artist / Title / Genre / Comment back to the file

**Organising**
- Playlist panel for building a set in order; saved playlists and smartlists (stored search rules)
- Search by text, Traktor colour, own rating and colour; Advanced Search with numeric comparisons
- Own *Rating* and *Color* per track, independent of Traktor
- Dark and light theme

## Engineering

What is behind the features, and where to look:

| Area | What | Where |
|---|---|---|
| Architecture | Logic in `core/` (no widgets, unit-tested), PyQt5 UI in `ui/`. Embedding analysis in a separate process at low CPU and I/O priority, with crash recovery, so the UI and Traktor stay responsive | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| ML inference | PANNs CNN14 exported to ONNX; DirectML / CUDA / CPU chosen at runtime, with CPU fallback. Audio decoding (soundfile + soxr) is bit-identical to `librosa.load`; ONNX output matches PyTorch within 1.1e-5 | [core/embeddings.py](src/songselector/core/embeddings.py), [research note](docs/research/audio_embeddings.md) |
| Model reproducibility | The model is not in the repo; [scripts/export_cnn14_onnx.py](scripts/export_cnn14_onnx.py) rebuilds it from the published checkpoint (SHA-256 pinned) and checks it against PyTorch | [Getting the model](#getting-the-embedding-model) |
| Testing | About 190 pytest tests, including headless Qt GUI tests and a test of the analysis process; acceptance tests on the developer's real library are marked and kept out of CI | [tests/](tests/) |
| Release verification | Every exe runs a self-check *inside the packaged app* (imports, GUI flows, Rekordbox reader, real GPU inference) and a native-window smoke test before it is published | [selfcheck.py](src/songselector/selfcheck.py), [verify_release.ps1](scripts/verify_release.ps1) |
| CI/CD | GitHub Actions: ruff, pytest on Windows, pip-audit, gitleaks over the full history, weekly scheduled run. `main` only accepts pull requests with green checks. A version tag builds, verifies and publishes the exe with a SHA-256 checksum | [ci.yml](.github/workflows/ci.yml), [release.yml](.github/workflows/release.yml) |
| Research | Can the sound predict a DJ's own ratings and colours? Four embedding models (CNN14, MusiCNN, Discogs-EffNet, OpenL3) compared with artist-grouped validation and bootstrap intervals. The answer was mostly no (rating AUC ≈ 0.6 for all four), so the feature was put on hold rather than shipped | [docs/research/](docs/research/) |

## Install

1. Download `SongSelector-<version>.exe` from the [latest release](https://github.com/csipapicsa/SongSelector/releases/latest)
   and put it in its own folder. It is self-contained (no Python needed). Windows SmartScreen will
   warn because the exe is not code-signed; check it against `SHA256SUMS.txt` from the same release.
2. For audio similarity, add the embedding model (next section). Everything else works without it.

The exe stores its data **next to itself**:

| File | Content |
|---|---|
| `SongSelector_settings.json` | Columns, search settings, tempo, colouring |
| `library.sqlite` | Every track loaded, your own ratings and colours, playlists and smartlists |
| `embeddings.sqlite` | Audio embeddings: a cache, safe to delete, rebuilt in the background |
| `models\cnn14.onnx` | The embedding model, if you keep it here |

To upgrade, put the new exe in the same folder. Settings from versions before 1.1
(`SpotNextTrack_settings.json`) are taken over on the first start.

## Getting the embedding model

`cnn14.onnx` (327 MB) is built from the published PANNs checkpoint (Kong et al., 2020, weights
[CC BY 4.0](https://zenodo.org/records/3987831)). The export needs PyTorch, which the app does
not, so use a separate environment:

```powershell
py -3.11 -m venv .export-venv
.\.export-venv\Scripts\python -m pip install torch panns-inference==0.1.1 onnx onnxruntime
.\.export-venv\Scripts\python scripts\export_cnn14_onnx.py       # -> .appdata\models\cnn14.onnx
```

When running from source the app finds it there. For the exe, copy it to `models\cnn14.onnx` next
to the exe, or pick it with *Analysis → Choose embedding model…*.

Speed for a 6-minute track: about 1.4 s on a GTX 1650 Ti (0.6 s model, 0.8 s decoding), about 6.4 s
on the CPU. A first pass over 3,000 tracks takes 1–1.5 hours on that GPU; after that only new or
changed files are analysed. *Analysis → Analyse embeddings in background* pauses it.

## Using it

### Similarity map

The *Similarity map* tab (Ctrl+2; Ctrl+1 for the List) shows the analysed tracks of the List as it is
filtered now, so narrow the List first to explore one style.

| Action | Result |
|---|---|
| Hover / click a dot | Details; a click also lists its 15 most similar tracks (cyan rings) |
| Double-click in the matches list | Select that track and show its own matches |
| Drag a dot or a match | The files, e.g. onto a Traktor deck or playlist |
| Drop a track on the map | Select it and show its closest matches |
| Double-click a dot | Add to the playlist |
| Scroll / drag | Zoom / move |
| *Edges* menu | Lines to harmonic partners (tempo-adjusted keys), same colour or same rating, optionally only to the N most similar |
| *Groups* | Colour dots by unsupervised groups |
| *Closest matches: harmonic only* | Only harmonic partners, plus tracks without a key |
| *Re-arrange map* | Recompute the layout (a few minutes for 3,000 tracks) |

Distances on a 2D map are approximate; the closest-matches list uses the full embeddings.

### Playlists and smartlists

- **Playlist** tab: the set being built, in order. Drag rows to reorder; *Save as Playlist...* keeps a copy.
- **Browser** tab: *Track Collection* (All Tracks, Artists, Albums, Genres), your playlists, and
  **Traktor Playlists** / **Rekordbox Playlists** (read-only, kept up to date). Click an entry to
  filter the List, double-click to load it into the Playlist tab.
- A **smartlist** stores search rules, not tracks; it always shows what matches now.

### Search syntax

| Search bar | Matches |
|---|---|
| `tribal` | Text in the columns ticked under *Search Columns* |
| `color:blue`, `color:red,orange`, `-color:blue`, `color:none` | Traktor colour |
| `sscolor:blue`, `-sscolor:none` | Your own colour |

*Advanced Search* adds numeric comparisons (e.g. own rating at least 4). Setting a row's column to
*None* switches that row off without losing it.

### Configuration

| Setting | How |
|---|---|
| Traktor collection | Auto-detected under `Documents\Native Instruments\Traktor*\`. Change via *Import → Link Traktor collection…* |
| Rekordbox library | Auto-detected from Rekordbox's settings, else `%APPDATA%\Pioneer\rekordbox\master.db`. Change via *Import → Link Rekordbox library…* |
| Data folder | `SONGSELECTOR_APP_DATA_DIR` environment variable |

## Development

Requirements: Windows, Python 3.11 (64-bit) available as `py -3.11`.

```powershell
.\scripts\setup.ps1                  # create .venv, install pinned dependencies
.\.venv\Scripts\Activate.ps1
python -m songselector               # run from source; data goes to .appdata\ (git-ignored)
.\scripts\test.ps1                   # pytest; pass options through, e.g. -k color
python -m ruff check src tests       # lint
.\scripts\build.ps1                  # -> dist\SongSelector-<version>.exe
.\scripts\verify_release.ps1         # self-check inside the exe + native window test
                                     # add -Model <path>\cnn14.onnx to include GPU inference
```

Set `SONGSELECTOR_CNN14_ONNX` to the model path to also run the real-model test.

**Releases** are built by GitHub Actions: bump `__version__` in
[src/songselector/\_\_init\_\_.py](src/songselector/__init__.py) and rename the changelog's
`[Unreleased]` section in a pull request, merge it, then tag the merge commit (`git tag vX.Y.Z`,
`git push origin vX.Y.Z`). The workflow checks that the tag matches the code and is on `main`, runs
the tests, builds and verifies the exe and publishes it with its checksum and the changelog section
as notes. Pull requests that change the packaging run the same build as a dry run.

```text
src/songselector/
    app.py         Entry point
    config.py      Constants, column layout, app-data location
    env.py         Environment variables
    selfcheck.py   End-to-end check that runs inside the packaged exe
    core/          Logic without widgets: keys, tags, Traktor/Rekordbox readers, embeddings, similarity
    ui/            PyQt5 main window, similarity map, dialogs
tests/             pytest suite
packaging/         PyInstaller spec and launcher
scripts/           setup / test / build / verify / model export
docs/              Architecture, backlog, research notes, daily worklogs
```

More: [CHANGELOG.md](CHANGELOG.md), [docs/BACKLOG.md](docs/BACKLOG.md) (known issues and plans),
[docs/worklogs/](docs/worklogs/) (what was done each day, and why).

## License

GPL-3.0 (PyQt5 and other bundled libraries are GPL, so the exe is too). The CNN14 weights are by
Kong et al., [PANNs](https://github.com/qiuqiangkong/audioset_tagging_cnn), CC BY 4.0.

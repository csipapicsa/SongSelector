# SongSelector

[![CI](https://github.com/csipapicsa/SongSelector/actions/workflows/ci.yml/badge.svg)](https://github.com/csipapicsa/SongSelector/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/csipapicsa/SongSelector)](https://github.com/csipapicsa/SongSelector/releases/latest)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue)
![Windows](https://img.shields.io/badge/platform-Windows-lightgrey)

A Windows desktop app that helps DJs pick the next track. It sits next to Traktor or Rekordbox, reads
their libraries automatically, and answers three questions:

- **Will it mix in key at the tempo I'm playing?** With Key Lock off, speeding a track up raises its
  pitch. SongSelector shows every track's key *at the current master tempo*, in Musical, Camelot and
  Open Key notation, and recalculates the whole library as you move the tempo slider.
- **What sounds like this track?** Neural audio models (PANNs CNN14, LAION CLAP, Microsoft CLAP, run
  through ONNX Runtime on the GPU) turn every track into embeddings in the background. A similarity map
  and a closest-matches list then show tracks that *sound* alike, whatever their tags say.
- **Which of my tracks sound like *this*?** Type a description, *"funky breakbeat with a groovy bassline"*,
  and the CLAP models find the closest tracks in your library.

## Features

**Harmonic mixing**
- Tempo-adjusted key for every track: `semitones = round(12 · log2(target / original BPM))`
- Harmonic partners on the Camelot wheel (perfect, ±1, scale change, energy boost and four more mix
  types) as edges on the map and as a filter for the closest matches

**Audio similarity and free-text search**
- Three embedding models to choose from: CNN14 (sound similarity, 5 s windows), LAION CLAP and Microsoft
  CLAP (sound *and* text in one space, 10 s / 7 s windows). You pick which ones are analysed and which one
  the map uses; each track is decoded once for all of them, in a low-priority background process, on the
  GPU through DirectML (any DirectX 12 card) or on the CPU
- **Search by description:** a typed prompt is turned into a CLAP text vector and the closest tracks are
  listed; prompts can be saved, results dragged onto Traktor
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
| ML inference | Three models exported to ONNX, every one taking raw audio (LAION's spectrogram built into the graph); DirectML / CUDA / CPU chosen at runtime, batch sizes measured per model. Text encoders run in their own process with the `tokenizers` library, no PyTorch in the app | [core/embeddings.py](src/songselector/core/embeddings.py), [core/text_search.py](src/songselector/core/text_search.py), [research note](docs/research/text_search_clap.md) |
| Model choice by measurement | CPU and GPU cost of LAION vs Microsoft CLAP measured before any app work; a broken model (collapsed embeddings) caught and excluded | [docs/research/text_search_clap.md](docs/research/text_search_clap.md) |
| Model reproducibility | No model is in the repo; export scripts rebuild them from the published weights and check every export against PyTorch (and LAION's audio side against transformers' own feature extractor) | [Getting the models](#getting-the-embedding-models) |
| Testing | About 200 pytest tests, including headless Qt GUI tests and a test of the analysis process; acceptance tests on the developer's real library are marked and kept out of CI | [tests/](tests/) |
| Release verification | Every exe runs a self-check *inside the packaged app* (imports, GUI flows, Rekordbox reader, real GPU inference) and a native-window smoke test before it is published | [selfcheck.py](src/songselector/selfcheck.py), [verify_release.ps1](scripts/verify_release.ps1) |
| CI/CD | GitHub Actions: ruff, pytest on Windows, pip-audit, gitleaks over the full history, weekly scheduled run. `main` only accepts pull requests with green checks. A version tag builds, verifies and publishes the exe with a SHA-256 checksum | [ci.yml](.github/workflows/ci.yml), [release.yml](.github/workflows/release.yml) |
| Research | Can the sound predict a DJ's own ratings and colours? Four embedding models (CNN14, MusiCNN, Discogs-EffNet, OpenL3) compared with artist-grouped validation and bootstrap intervals. The answer was mostly no (rating AUC ≈ 0.6 for all four), so the feature was put on hold rather than shipped | [docs/research/](docs/research/) |

## Install

1. Download `SongSelector-<version>.exe` from the [latest release](https://github.com/csipapicsa/SongSelector/releases/latest)
   and put it in its own folder. It is self-contained (no Python needed). Windows SmartScreen will
   warn because the exe is not code-signed; check it against `SHA256SUMS.txt` from the same release.
2. On the first start the app offers to download the embedding models (*Analysis → Download models…*,
   1.6 GB in all, or just the ones you want). They are switched on and your tracks are analysed in the
   background. Everything else works without them.

The exe stores its data **next to itself**:

| File | Content |
|---|---|
| `SongSelector_settings.json` | Columns, search settings, tempo, colouring |
| `library.sqlite` | Every track loaded, your own ratings and colours, playlists and smartlists |
| `embeddings.sqlite` | CNN14 embeddings: a cache, safe to delete, rebuilt in the background |
| `embeddings-laion-clap.sqlite`, `embeddings-ms-clap.sqlite` | The same for the CLAP models |
| `models\` | The model files (next section) |

To upgrade, put the new exe in the same folder. Settings from versions before 1.1
(`SpotNextTrack_settings.json`) are taken over on the first start.

## Getting the embedding models

**The app downloads them:** *Analysis → Download models…* fetches the files from the project's
[`models-v1` release](https://github.com/csipapicsa/SongSelector/releases/tag/models-v1) into the `models`
folder next to the app's data, resumes an interrupted download, and checks each file's SHA-256 before using it.

The files are ONNX exports of published weights; the release lists sources and licences. To rebuild them
yourself (every export is checked against the original PyTorch model), use a separate environment, since
the exports need PyTorch and the app does not. They go to `.appdata\models\`, where the app looks when run
from source; `scripts\publish_models.ps1 -Folder <folder>` checks them against the app's checksums and
publishes the release.

| Model | Files | Weights | Export |
|---|---|---|---|
| CNN14 | `cnn14.onnx` (327 MB) | PANNs, Kong et al. 2020, [CC BY 4.0](https://zenodo.org/records/3987831) | `scripts\export_cnn14_onnx.py` (needs `torch panns-inference==0.1.1 onnx onnxruntime`) |
| LAION CLAP | `clap-laion-audio.onnx`, `clap-laion-text.onnx`, `clap-laion-tokenizer.json` (630 MB) | [`laion/clap-htsat-unfused`](https://huggingface.co/laion/clap-htsat-unfused), Apache 2.0 | `scripts\export_clap_onnx.py --models laion` |
| Microsoft CLAP | `clap-ms-audio.onnx`, `clap-ms-text.onnx`, `clap-ms-tokenizer.json` (640 MB) | [`microsoft/msclap`](https://huggingface.co/microsoft/msclap) 2023, MS-PL | `scripts\export_clap_onnx.py --models ms` |

```powershell
py -3.12 -m venv .export-venv
.\.export-venv\Scripts\python -m pip install "torch>=2.6" panns-inference==0.1.1 msclap==1.3.4 onnx onnxruntime
.\.export-venv\Scripts\python scripts\export_cnn14_onnx.py
.\.export-venv\Scripts\python scripts\export_clap_onnx.py
```

Then switch the models on under *Analysis → Embedding models*. Each track is decoded once for all of
them. Speed for a 6-minute track on a GTX 1650 Ti (DirectML): CNN14 0.6 s, LAION CLAP about 2.2 s,
Microsoft CLAP about 2.8 s, plus 0.8 s decoding; on the CPU several times that. After the first pass
only new or changed files are analysed. *Analysis → Analyse embeddings in background* pauses it.

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

### Search by description and choosing models

The **Sounds like:** bar above the List is the quickest way: type what a track should sound like (or pick a
saved prompt from its dropdown) and press Enter. The List then shows the closest tracks of the chosen CLAP
model, best first in the `#` column; ★ saves the prompt, ✕ deletes it, *Show all tracks* goes back.
*Analysis → Search by description…* (Ctrl+Shift+F) opens the same search in its own window, with scores.
Describe the sound (instruments, textures, energy, mood: *"warm pads, slow and dreamy"*, *"distorted
acid line, hypnotic"*); *"This audio is a drum and bass song."* style sentences also work well. Save
prompts you want to repeat, double-click a result to select it in the List, drag results onto Traktor.
Only tracks already analysed with that model can be found.

*Analysis → Embedding models* sets which models are kept up to date; *Similarity model* sets which one the
map, the closest matches and the groups use. Each model keeps its own map layout. *Parallel analysis* sets how
many tracks are analysed at once (automatic: 2 on a GPU). On laptops with two GPUs the analysis uses the
high-performance one, and each model's batch size is measured once on your machine.

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

Set `SONGSELECTOR_CNN14_ONNX` to `cnn14.onnx`, and `SONGSELECTOR_CLAP_MODELS` to the folder with the CLAP
files, to also run the real-model tests.

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

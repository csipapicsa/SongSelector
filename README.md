# Traktor Key Calculator

A Windows desktop tool for DJs. Given a track's original BPM and key, it shows the
key the track will play in at another tempo, assuming **Key Lock is off**, so you
can pick harmonically compatible tracks at the tempo you are actually playing.

- Library and playlist panels with Musical, Camelot and Open Key notation
- Master-tempo slider that recalculates every row live
- Drag and drop MP3/WAV/FLAC import, reading BPM, key, rating, etc. from file tags
- Missing metadata filled in from Traktor's `collection.nml` (read-only)
- Traktor category colors, key colors, text, numeric, rating and color search
- Library and playlist are restored on restart; Shift/Ctrl multi-selection; *Delete* removes rows from a list
  (never files); *right-click → Delete duplicates from the list*
- Your own *Rating - Song Selector* and *Color - Song Selector*, independent of Traktor (right-click to set)
- Edit Artist / Title / Genre / Comment; the change is written into the audio file's tags
- Background audio embeddings (CNN14, one vector per 5 s) for every library track, CPU or NVIDIA GPU

Current version: **4.7.0** (see [CHANGELOG.md](CHANGELOG.md)).

## Quick start (development)

Requirements: Windows, Python 3.11 (64-bit) available as `py -3.11`.

```powershell
.\scripts\setup.ps1                  # create .venv and install pinned dependencies
.\.venv\Scripts\Activate.ps1
python -m traktor_key_calculator     # run the app from source
.\scripts\test.ps1                   # run the test suite (pytest)
```

When run from source, settings and imported tracks are stored in `.appdata\`
in the repo (git-ignored), so development never touches your real app data.

## Build and release

```powershell
.\scripts\build.ps1                  # -> dist\TraktorKeyCalculator-<version>.exe
.\scripts\verify_release.ps1         # headless self-check + real-window smoke test
                                     # add -Model <path>\cnn14.onnx to also test embeddings in the exe
```

The exe is self-contained (no Python needed). It stores its data **next to
itself**:

| File | Content |
|---|---|
| `SpotNextTrack_settings.json` | Column visibility, search settings, tempo, coloring |
| `library.sqlite` | Every track ever loaded, your Song Selector ratings/colors, the last saved Library and Playlist lists |
| `embeddings.sqlite` | Audio embeddings (a cache: safe to delete, it is rebuilt) |
| `models\cnn14.onnx` | The embedding model, if you keep it here (optional, see below) |
| `imported_tracks.json` | Imports from versions ≤ 4.5.0; read once on the first 4.6 start, then kept as a backup |

To upgrade an existing installation, put the new exe in the same folder as these
files (or copy them next to it). The Traktor collection is only ever read. Audio
files are written only when you edit Artist / Title / Genre / Comment, and then only those tags.

## Embedding analysis

The app computes PANNs CNN14 embeddings (one 2048-value vector per 5 seconds) for
every track in the library panel, in a background process at low priority. The
status bar shows progress, and *Analysis → Analyse embeddings in background* pauses it.

- **Model:** `cnn14.onnx` (327 MB, not in the repo or the exe). Default:
  `E:\GITHUB_E\MusicFindBoundaries\cnn14.onnx` (the DJ mix segmentation project's model).
  A `models\cnn14.onnx` next to the data, or *Analysis → Choose embedding model…*, takes precedence.
- **Speed (6-minute track):** about 6.4 s on the CPU, about 1.5 s on an NVIDIA
  GTX 1650 Ti. A first full pass over ~5,000 tracks takes hours, but only once;
  later only new or changed files are analysed.
- **GPU (from source):** see `requirements-gpu.txt`. Install `onnxruntime-gpu==1.22.0`
  in place of `onnxruntime`, and provide the CUDA 12 / cuDNN 9 DLLs, e.g. by setting
  `TRAKTOR_CUDA_DLL_DIR` to the `torch\lib` folder of a CUDA PyTorch install.
  The release exe uses the CPU.

Release checklist:

1. Bump `__version__` in `src/traktor_key_calculator/__init__.py`.
2. Add an entry to `CHANGELOG.md`.
3. `.\scripts\test.ps1`, then `.\scripts\build.ps1`, then `.\scripts\verify_release.ps1`.
4. Commit, tag `vX.Y.Z`, and attach the exe to a GitHub release (exes are not committed).

## Project layout

```text
src/traktor_key_calculator/
    app.py              Entry point: QApplication + main window
    config.py           Constants, column layout, color tables, app-data location
    selfcheck.py        End-to-end check that runs inside the packaged exe
    core/               Logic without UI widgets (keys, tags, Traktor NML, search)
    ui/                 PyQt5 main window, tree widgets, dialogs, delegates
    data/music_test.csv Bundled default track library
tests/                  pytest suite (unittest-style test classes)
packaging/              PyInstaller spec and launcher script
scripts/                setup / test / build / verify PowerShell scripts
docs/                   Architecture notes, backlog, project history
```

How the parts fit together is described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Known issues and planned work are in [docs/BACKLOG.md](docs/BACKLOG.md).

## Search syntax

| Search bar | Matches |
|---|---|
| `tribal` | text in the columns ticked under *Search Columns* |
| `color:blue`, `color:red,orange`, `-color:blue`, `color:none` | Traktor category color |
| `sscolor:blue`, `-sscolor:none`, ... | *Color - Song Selector* (same names) |

*Advanced Search* can also compare *Rating - Song Selector* numerically (e.g. at least 4)
and *Color - Song Selector* by color name.

## Configuration

| Setting | How |
|---|---|
| Traktor collection | Auto-detected (`E:\DJ\TRAKTOR\collection.nml`, then `Documents\Native Instruments\Traktor*\`). Change via *Import → Link Traktor collection…* |
| Data directory | Set the `TRAKTOR_APP_DATA_DIR` environment variable to override |

## Tests

`.\scripts\test.ps1` runs 75 tests, plus one with the real model when
`$env:TKC_CNN14_ONNX = '<path>\cnn14.onnx'` is set, including headless Qt GUI tests. Two tests
also use real files on the original developer machine (`E:\DJ\...`) and are
skipped automatically when those files are absent. Pass pytest options through,
e.g. `.\scripts\test.ps1 -k color`.

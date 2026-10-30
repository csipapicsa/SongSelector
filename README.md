# Traktor Key Calculator

A Windows desktop tool for DJs. Given a track's original BPM and key, it shows the
key the track will play in at another tempo, assuming **Key Lock is off**, so you
can pick harmonically compatible tracks at the tempo you are actually playing.

- Library and playlist panels with Musical, Camelot and Open Key notation
- Master-tempo slider that recalculates every row live
- Drag and drop MP3/WAV/FLAC files or whole folders (with subfolders), reading BPM, key, rating, etc. from file tags
- Missing metadata filled in from Traktor's `collection.nml` (read-only)
- Traktor category colors, key colors, text, numeric, rating and color search
- Library and playlist are restored on restart; Shift/Ctrl multi-selection; *Delete* removes rows from a list
  (never files); *right-click → Delete duplicates from the list*
- Your own *Rating - Song Selector* and *Color - Song Selector*, independent of Traktor (right-click to set)
- Edit Artist / Title / Genre / Comment; the change is written into the audio file's tags
- Background audio embeddings (CNN14, one vector per 5 s) for every library track, on the GPU (DirectML) or CPU
- Dark grey theme (*View → Dark theme* toggles light)
- **Similarity map**: tracks as dots, similar ones close together; closest matches, harmonic edges

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
- **Device:** the GPU through DirectML (any DirectX 12 graphics card, no CUDA needed),
  otherwise the CPU. The status bar shows which one is used.
- **Speed (6-minute track):** about 1.4 s on a GTX 1650 Ti (0.6 s model + 0.8 s decoding),
  about 6.4 s on the CPU. A first pass over ~3,000 tracks takes about 1–1.5 h on the GPU;
  later only new or changed files are analysed.
- **Impact on other programs:** the analysis runs as a Windows background process (low CPU
  and disk priority), so Traktor or a media player reading the same disk go first.
- **CUDA (optional, from source):** see `requirements-gpu.txt`. Not needed for speed.

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

## Similarity map

*Similarity map* tab next to *List* (Ctrl+2 / Ctrl+1). It shows the analysed tracks of the list as
it is filtered now (search, colours, Advanced Search), so narrow the list first to explore a style.

| Action | Result |
|---|---|
| Hover a dot | Details; choose which in *View → Map hover details…* |
| Click | Label and details of the track; its 15 most similar tracks: cyan rings, list on the right |
| Click in the matches list | That track glows (magenta) and its edges show pale; the selection stays |
| Double-click in the matches list | Select that track (its own matches) |
| Drag a dot or matches | The files, e.g. into Traktor's deck or playlist |
| Drop a track on the map (e.g. from the playlist) | Selects it there and shows its closest matches |
| Column headers of the matches | Sort (click again to reverse) |
| Double-click a dot | Add to playlist |
| Right-click | The usual track menu (rating, colour, edit, remove) |
| Scroll / drag | Zoom / move |
| *Edges* menu | Lines to harmonic partners (tempo-adjusted keys), same colour, same rating |
| *to the N most similar* | Edges only to the N partners that sound most similar; more similar = more opaque |
| *Groups* | Colour dots by unsupervised groups: k-means, neighbour communities or map density |
| *Closest matches: harmonic only* | Only harmonic partners, plus tracks without a key in Traktor (*no key*) |
| Italic match | Already on the playlist |
| *Re-arrange map* | Recompute the layout from all analysed tracks (a few minutes for 3,000) |

Distances on any 2D map are approximate; the closest-matches list uses the full embeddings and
is exact. On the developer's library the map separated breakbeat and DnB with about 93 % purity,
from audio alone.

## Playlists and smartlists

The left pane has two tabs:

- **Playlist**: the set being built, in order (**#** column). Drag rows to reorder them; rows
  dragged in from the List are inserted where they are dropped. *Save as Playlist...* keeps a
  copy under *Playlists* in the Browser.
- **Browser**, as in Traktor: *Track Collection* (All Tracks, Artists, Albums, Genres) and
  *Playlists*. Click an entry, or drag it onto the List, to show only its tracks there (a
  playlist in its order, by **#**); *Show all tracks* above the List goes back. Double-click a
  playlist or smartlist, or drag it onto the Playlist tab, to load it there (replace or add).
  Drag tracks onto a playlist to add them. Right-click for new, rename, duplicate, delete.
- A **smartlist** stores Complex Search rows, not tracks: it always lists the tracks that match
  them now. Create one with *Save as Smartlist...* in the Complex Search dialog or *New
  smartlist...* in the Browser; *Edit rules...* changes it.

Saved playlists and smartlists live in `library.sqlite`. While the List shows one of your
playlists, tracks dropped onto it (from Traktor, Explorer or the Playlist tab) are added to it.

**Traktor Playlists** in the Browser lists Traktor's playlists and folders from `collection.nml`
(read-only, updated when Traktor saves). They show and load like your own playlists;
right-click to import their missing tracks or copy one to your playlists. Traktor's smartlists
are listed but not evaluated yet.

## Groups in the List

The **Group** column shows each track's group on the similarity map (the map's *Groups*
setting; 1 = largest group). Sort by it to keep similar-sounding tracks together. **Group
colours** above the List colours the rows like the map's dots instead of by Traktor colour; if
the map's grouping is off, it turns on *Neighbour communities*. Group numbers change when the
tracks are grouped again (another method or setting, newly analysed tracks).

## Search syntax

| Search bar | Matches |
|---|---|
| `tribal` | text in the columns ticked under *Search Columns* |
| `color:blue`, `color:red,orange`, `-color:blue`, `color:none` | Traktor category color |
| `sscolor:blue`, `-sscolor:none`, ... | *Color - Song Selector* (same names) |

*Advanced Search* can also compare *Rating - Song Selector* numerically (e.g. at least 4)
and *Color - Song Selector* by color name. Setting a row's column to *None* switches that row off:
its condition and value stay (and are saved) but do not filter.

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

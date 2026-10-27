# Architecture

This document explains how the application works internally, for anyone who
needs to change it.

## The core idea

With Key Lock off, playing a track faster or slower shifts its pitch:

```text
semitones = round(12 * log2(target_bpm / original_bpm))
new_key   = original_key shifted by that many semitones (major/minor unchanged)
```

Example: C major at 100 BPM played at 150 BPM gives 12 * log2(1.5) = 7.02, so 7
semitones up, which is G major. The result is rounded to the nearest semitone.
That matches what you hear only when the shift is close to a whole semitone;
in between, the track is detuned.

This lives in `core/key_calculator.py` (`KeyCalculator`). The new key is then
shown in Camelot (`8B`) and Traktor Open Key (`1d`) notation.

## Layers

```text
app.py ──> ui.main_window.TraktorKeyCalculator   (QMainWindow, owns all state)
              │
              ├── ui/*            widgets, dialogs, painting
              └── core/*          logic without widgets; easy to unit-test
config.py                         shared constants, used by both layers
```

`core/` modules do not import from `ui/`. Keep it that way: new logic should go
in `core/` with a unit test, and the UI should only call it. (`config.py` still
imports `QColor` for color tables. This is a known wart, see BACKLOG.)

### core/

| Module | Responsibility |
|---|---|
| `key_formats.py` | Parse any key notation (`C#m`, `Bm`, `8A`, `3m`, Traktor NML int) to `(note, 'major'/'minor')`; parse BPM strings |
| `key_calculator.py` | Tempo → semitone shift, transpose, Camelot / Open Key lookup |
| `key_tables.py` | Static key lookup tables (also contains unused leftovers from the thesis project) |
| `audio_metadata.py` | Read ID3 / FLAC / WAV tags with mutagen into `config.AudioMetadata` |
| `traktor_collection.py` | Read-only, cached index of Traktor's `collection.nml`; lookup by exact path, then by unique filename + file size |
| `track_import.py` | `TrackImporter` merges tag data with collection data; `merge_tracks`, `drop_duplicate_paths`, `enrich_ratings`; `ImportedTrackStore` reads the pre-4.6 `imported_tracks.json` |
| `library_store.py` | `LibraryStore`: SQLite file with the app's own collection (every track ever loaded), the user's Song Selector rating/color, and the saved Library / Playlist lists |
| `tag_writer.py` | `write_tags`: writes Artist / Title / Genre / Comment into MP3 (ID3), WAV (ID3 chunk) and FLAC (Vorbis) files. The only code that writes audio files |
| `harmonic.py` | `mix_type(from, to)`: Mixed In Key harmonic relation between Camelot keys, with weights (from the thesis project) |
| `similarity.py` | `track_vectors` (mean+std, centred, unit length), `nearest`, `tsne_layout` (numpy), `place_new`, map edge rules |
| `embeddings.py` | CNN14 embeddings: `load_audio`, `Cnn14Embedder` (onnxruntime, GPU if available), `EmbeddingStore` (`embeddings.sqlite`), `run_analysis` (entry point of the analysis process). Must not import Qt |
| `data_manager.py` | Loads the library CSV (bundled `data/music_test.csv` by default) into a pandas DataFrame |
| `search_filters.py` | Complex Search conditions (contains, is, >, <, >=, <=), number parsing with decimal commas |
| `color_search.py` | `color:blue,red`, `-color:x`, `color:none` query parsing and replacement |

### ui/

| Module | Responsibility |
|---|---|
| `main_window.py` | The main window: layout, BPM slider, search, sorting, import, settings persistence |
| `tree_widgets.py` | `PoolTreeWidget` (library, right) and `PlaylistTreeWidget` (left); drag and drop between them and from Explorer |
| `delegates.py` | Paints the Traktor category color dot |
| `menu_bar.py` | Menu definitions, emitted as signals |
| `advanced_search_dialog.py` | Complex Search dialog (`AdvancedSearchDialog`, `AdvancedSearchRow`) |
| `coloring_dialog.py` | Choose category colors or key colors |
| `music_paths_dialog.py` | Music path settings dialog |
| `track_info_dialog.py` | Edit Artist / Title / Genre / Comment of one file |
| `similarity_map.py` | The *Similarity map* tab: dots, closest matches, edges; `build_map_data` runs in a thread |
| `map_settings_dialog.py` | Choose the map's hover details |
| `embedding_worker.py` | `EmbeddingAnalyzer`: starts and supervises the analysis process, turns its events into Qt signals |

### Right-click menu (both panels)

`TraktorKeyCalculator.track_context_menu(tree)` acts on all selected rows (Shift/Ctrl+click): *Edit track info…* (the clicked row), *Remove from library/playlist* (also the Delete key),
*Rating - Song Selector*, *Color - Song Selector*, and in the library panel
*Delete duplicates from the list*.

## Data flow

```text
start ──> library.sqlite: saved 'Library' list ──> DataFrame (window.table) ──> _track_item() per row ──> tree rows
          (first start only: data/music_test.csv          │                        │
           + imported_tracks.json)                        │                        └─ KeyCalculator at slider BPM
                                                          └─ saved 'Playlist' list ──> left panel
Dropped audio file ──> TrackImporter.read()
                         ├─ tags (mutagen)
                         └─ fallback: TraktorCollection.find()  (key, BPM, color, rating)
                       ──> merge_tracks() into window.table ──> LibraryStore.save_list('Library')
```

- **Library CSV columns** used: `Artist, Title, File_Path, Comment, BPM, Color,
  Musical_Key_Base, BaseMinorOrMajor, Genre`, plus optional `Album, Rating`.
  Imported rows also carry `Key_Source`, `BPM_Source`, `Color_Source` (shown as
  row tooltips) and `Imported`.
- **Moving the slider** re-runs `_track_item()` for all rows. Nothing is cached
  per tempo.
- **Duplicates:** rows are matched by `canonical_path()` (normalised, case-folded
  Windows path). Dropping a file again updates its row instead of adding one.
  Rows with a repeated path can still come from a loaded CSV. *Right-click →
  Delete duplicates from the list* removes them (`drop_duplicate_paths`), keeping
  the first row. Wherever a path occurs more than once, the **first row wins**:
  `_rows_by_path`, `LibraryStore.upsert_tracks` and dedupe all follow this rule.

## Persistence

`config.APP_DATA_DIR` resolves to (first match wins):

1. `TRAKTOR_APP_DATA_DIR` environment variable (used by tests and verification)
2. The folder containing the exe (when frozen by PyInstaller)
3. `<repo>/.appdata` when running from a source checkout
4. `~/.traktor_key_calculator` otherwise

It holds:

| File | Content | Written |
|---|---|---|
| `SpotNextTrack_settings.json` | UI settings (name is historical, kept for existing installs) | on close |
| `library.sqlite` | Collection, Song Selector rating/color, saved lists (see below) | on every change |
| `embeddings.sqlite` | Audio embeddings, a cache that can be deleted and recomputed (see below) | by the analysis process |
| `models/cnn14.onnx` | Optional location of the embedding model. Order: model chosen in *Analysis*, this file, then `config.DEFAULT_EMBEDDING_MODEL` (`TRAKTOR_EMBEDDING_MODEL=none` disables the default; tests and verification do) | never |
| `imported_tracks.json` | Imports saved by versions ≤ 4.5.0 | never; read once, kept as a backup |

### library.sqlite

Modelled on how Traktor and Rekordbox separate the collection from playlists:

- `tracks`: **the collection**, every track the app has ever loaded, one row per
  `path_key` (= `canonical_path(file_path)`). Known fields have their own columns
  so they can be queried and indexed. Any other field (`Key_Source`, CSV extras,
  ...) goes in the JSON `extra` column, so no field is lost. Tracks are never
  deleted when they leave a list.
- `lists` + `list_tracks`: **saved lists**, ordered `path_key`s per list name.
  `Library` = right panel, `Playlist` = left panel. More playlists can be added
  later without a schema change.
- `tracks.ss_rating` / `tracks.ss_color` (schema 2): **the user's own** rating
  (1–5) and color (1–9, as in `COLOR_NAMES`), shown as *Rating - Song Selector*
  and *Color - Song Selector*. Only `set_user_fields` writes them. Upserting
  metadata (imports, CSV, Refresh) never overwrites them, and `_with_user_fields`
  lays them over tables rebuilt from a CSV. *Rating* and *Color* stay the values
  from file tags / Traktor.
- `meta`: `schema_version` (currently 2). To change the schema, bump it and add
  the step to `LibraryStore._migrate`, which upgrades existing files in place.

On start, the window restores both lists (`_restore_lists`). Only on the very
first start, when no `Library` list exists yet, is the library built from
`data/music_test.csv` plus the old `imported_tracks.json`. After that, *Refresh*
rebuilds the list from those sources on request, and *Load CSV* replaces it.
SQLite was chosen after measuring on the real 5,100-track library: loading it
takes 10 ms in SQLite vs 18 ms in JSON, and updating one track 0.1 ms vs
22 ms, because JSON rewrites the whole file. Writes are transactional.

### embeddings.sqlite and the analysis process

Every track in the library panel gets PANNs CNN14 embeddings: one 2048-value
vector per 5 s of audio (background in `docs/research/audio_embeddings.md`).

- **Separate process.** `EmbeddingAnalyzer` (UI side) starts
  `core.embeddings.run_analysis` with `multiprocessing` (spawn). The process loads
  the model, decodes files, writes results to `embeddings.sqlite` and reports
  events through a queue, which a 200 ms `QTimer` polls. Why not a thread:
  (1) a decoder crash on a broken file only kills the process: the analyzer records
  that file as failed and restarts the process, giving up after 3 crashes in a row;
  (2) no competition with the UI for the Python GIL; (3) the process runs at
  *below normal* priority with half the CPU cores.
- **Jobs go to the process 4 at a time** (`IN_FLIGHT`). Queuing thousands at
  once filled the OS pipe, and the queue's feeder thread then kept the app from
  exiting (regression test: `test_app_can_exit_after_stopping_with_a_large_backlog`).
- **Up to date = same file size and mtime** (`file_fingerprint`). Undecodable
  files are stored with `error` and retried only when the file changes. A tag
  edit updates the fingerprint, because the audio itself did not change.
- **Storage:** float16 + zlib, lossless; about 17–21 % of raw size, because ~87 %
  of the values are exactly 0. A 6-minute track takes ~50 KB. WAL mode lets the
  UI read while the process writes.
- **Device:** CUDA, then DirectML, then CPU, whichever the installed onnxruntime
  supports. The default package is `onnxruntime-directml`. Batch sizes are per device
  (`BATCH_SIZES`), and batches are padded to a fixed shape, because GPU providers re-plan
  the model for every new input shape.
- **Background process:** `_lower_process_priority` uses `PROCESS_MODE_BACKGROUND_BEGIN`
  (very low I/O priority) and then `BELOW_NORMAL_PRIORITY_CLASS`, in that order (background
  mode resets the class). The ctypes argument types must be declared, or the 64-bit
  process handle is truncated and the call silently fails.
- **Disk writes:** the process keeps one connection (`EmbeddingStore(keep_open=True)`) with
  `synchronous=NORMAL`, so it syncs at WAL checkpoints only. UI-side stores open and close a
  connection per call, so no file stays locked.
- `launcher.py` calls `multiprocessing.freeze_support()` first and `__main__.py`
  has a `__name__` guard, because the spawned process re-imports the entry module.

### Similarity map

- **Same rows as the list.** `TraktorKeyCalculator._refresh_map` passes the texts of the visible
  list rows to the map (`set_tracks`), at the end of every `filter_items`, but only while the map
  tab is shown. Filters, tempo-adjusted keys and colours therefore always match the list.
- **Layout** (`build_map_data`, background thread): load all embeddings, `track_vectors`, then
  `tsne_layout` if there is no stored layout or it covers less than half of the analysed tracks.
  Otherwise `place_new` positions the new tracks. Positions are stored in `embeddings.sqlite`
  (`map_layout`) and only `save_layout` replaces them, so filtering never moves dots.
- **Edges** (`SimilarityMapWidget._edges`): tracks are grouped by tempo-adjusted Camelot key,
  colour and rating, and partners are looked up per group (no all-pairs loop); one edge per
  pair, capped at `MAX_EDGES`.
- **Choices backed by measurements** (2026-10-27, ~450–700 analysed tracks; see
  `docs/research/audio_embeddings.md`): t-SNE kept 41–47 % of each track's 10 true neighbours as
  map neighbours (UMAP 37–42 %, PCA 26 %). The numpy t-SNE matches scikit-learn's quality
  (41.5 % vs 42.6 %); for 3,000 tracks it takes about 3 minutes, hence the cache.

### MSVC runtime conflict (PyQt5 ↔ onnxruntime)

The PyQt5-Qt5 wheel ships MSVC runtime DLLs from 2020 (14.26). If they load first
in a process, onnxruntime crashes with an access violation. This happens in
PyInstaller's build step, and the old DLLs would end up in the exe.
`scripts/update_qt_msvc_runtime.ps1` (run by `setup.ps1`, checked by `build.ps1`)
replaces them with the system's current v14 runtime, which Microsoft keeps
backward compatible.

### Theme

`ui/theme.py`: Qt Fusion style with a dark (default) or light palette, `apply_theme` works
at runtime. Status messages must use `status_style('info'|'ok'|'warning'|'error')`, never
fixed colours, so they stay readable on both backgrounds. Row tint opacity comes from
`row_tint_alpha()`.

## External files

- `collection.nml` (Traktor) is **never written**.
- Audio files are written **only** when the user edits Artist / Title / Genre / Comment
  (`core/tag_writer.py`). Just those tags change, and the ID3 version (v2.3 / v2.4)
  is kept. The file is then re-read like a fresh import, so the edit also survives
  *Refresh* / *Load CSV*. If writing fails, nothing in the library changes.
  Traktor shows the new tags once it re-reads the file.

## Testing

- `tests/test_imports.py`: tag parsing, key notations, collection fallback,
  relocation matching, persistence, drag-and-drop GUI flows, color painting.
  Also exports the `tagged_file()` / `make_collection()` fixtures used by other
  test modules.
- `tests/test_numeric_search.py`, `test_ratings.py`, `test_color_search.py`,
  `test_library.py`, `test_song_selector_fields.py`: one feature each, logic plus GUI.
- `tests/test_embeddings.py`: pipeline, storage, and the analysis process with
  fake embedders (module-level classes, because they run in the spawned process),
  including crash recovery and clean exit. `RealModelTests` runs the real CNN14
  only when `TKC_CNN14_ONNX` points at `cnn14.onnx`.
- `tests/conftest.py` makes Qt headless (`QT_QPA_PLATFORM=offscreen`) and points
  `TRAKTOR_APP_DATA_DIR` at a temporary folder **before** the package is imported.
- `selfcheck.py` repeats the key scenarios inside the frozen exe, because
  PyInstaller builds can break things that pass from source (missing data files,
  hidden imports). `scripts/verify_release.ps1` runs it. With `-Model <cnn14.onnx>`,
  it also runs a real embedding analysis in the exe's analysis process.

## Packaging

`packaging/TraktorKeyCalculator.spec` builds a one-file, windowed exe from
`packaging/launcher.py`. The library CSV is bundled as
`traktor_key_calculator/data/music_test.csv` inside the archive. `config.py` finds
it relative to its own `__file__`, which works both from source and frozen.
Large unused libraries are excluded explicitly to keep the exe size down.

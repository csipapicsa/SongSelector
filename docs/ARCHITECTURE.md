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
app.py ──> ui.main_window.MainWindow   (QMainWindow, owns all state)
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
| `rekordbox_library.py` | Read-only playlists (folders, order, file of each track) from Rekordbox's encrypted `master.db`, via `sqlcipher3` and the published key; reads a temporary copy. Same shape as `TraktorCollection`, so `ui/traktor_watcher.py` and the Browser serve both |
| `track_import.py` | `TrackImporter` merges tag data with collection data; `merge_tracks`, `drop_duplicate_paths`, `enrich_ratings`; `ImportedTrackStore` reads the pre-4.6 `imported_tracks.json` |
| `library_store.py` | `LibraryStore`: SQLite file with the app's own collection (every track ever loaded), the user's Song Selector rating/color, and the saved Library / Playlist lists |
| `tag_writer.py` | `write_tags`: writes Artist / Title / Genre / Comment into MP3 (ID3), WAV (ID3 chunk) and FLAC (Vorbis) files. The only code that writes audio files |
| `harmonic.py` | `mix_type(from, to)`: Mixed In Key harmonic relation between Camelot keys, with weights (from the thesis project) |
| `similarity.py` | `track_vectors` (mean+std, centred, unit length), `nearest`, `tsne_layout` (numpy), `place_new`, map edge rules |
| `embedding_models.py` | The embedding models (CNN14, LAION CLAP, Microsoft CLAP): files, sample rate, window, size, batch sizes, text settings, cache file. Must not import Qt |
| `embeddings.py` | Embeddings: `load_audio_rates` (one decode, several sample rates), `OnnxEmbedder` (any model, onnxruntime, GPU if available), `EmbeddingStore` (one cache file per model), `run_analysis` (entry point of the analysis process, all enabled models). Must not import Qt |
| `text_search.py` | Free-text search: `tokenize`, `TextEncoder` (CLAP text side, onnxruntime), `rank`, `run_text_encoder` (entry point of the text search process). Must not import Qt |
| `data_manager.py` | Loads a library CSV picked by the user (*Load CSV*) into a pandas DataFrame; `load_default_data` is the empty starting library |
| `search_filters.py` | Complex Search conditions (contains, is, >, <, >=, <=), number parsing with decimal commas |
| `color_search.py` | `color:blue,red`, `-color:x`, `color:none` query parsing and replacement |

### ui/

| Module | Responsibility |
|---|---|
| `main_window.py` | The main window: layout, BPM slider, search, sorting, import, settings persistence |
| `tree_widgets.py` | `PoolTreeWidget` (List view, right) and `PlaylistTreeWidget` (Playlist tab, left: reordering by drag); drag and drop between them and from Explorer |
| `list_browser.py` | `ListBrowser`, the Browser tab: Track Collection (all, artists, albums, genres) and saved playlists / smartlists; emits what was clicked, double-clicked or dropped |
| `saved_lists.py` | `SavedListsMixin` of the main window: shows a Browser entry in the List view (# column for playlists), loads it into the Playlist tab, saves / renames / deletes playlists and smartlists |
| `delegates.py` | Paints the Traktor category color dot |
| `menu_bar.py` | Menu definitions, emitted as signals |
| `advanced_search_dialog.py` | Complex Search dialog (`AdvancedSearchDialog`, `AdvancedSearchRow`); also edits a smartlist's rules |
| `coloring_dialog.py` | Choose category colors or key colors |
| `music_paths_dialog.py` | Music path settings dialog |
| `track_info_dialog.py` | Edit Artist / Title / Genre / Comment of one file |
| `similarity_map.py` | The *Similarity map* tab: dots, closest matches, edges; `build_map_data` runs in a thread |
| `map_settings_dialog.py` | Choose the map's hover details |
| `embedding_worker.py` | `EmbeddingAnalyzer`: starts and supervises the analysis process, turns its events into Qt signals |
| `text_search_worker.py`, `text_search_dialog.py` | The text search process (started on the first query) and the *Search by description* window |

### Playlist tracks in the library list

`filter_items` marks library rows whose track is on the playlist (`IN_PLAYLIST_ROLE`); they are
dimmed and italic (`_apply_text_colours`, which also owns the orange "missing key/BPM" colour) and
hidden only with *View → Hide playlist tracks in the library* (`settings['Hide playlist tracks']`).
Until 4.14.0 they were always hidden, which made searches miss them without notice.

### Right-click menu (both panels)

`MainWindow.track_context_menu(tree)` acts on all selected rows (Shift/Ctrl+click): *Edit track info…* (the clicked row), *Remove from library/playlist* (also the Delete key),
*Rating - Song Selector*, *Color - Song Selector*, and in the library panel
*Delete duplicates from the list*.

## Data flow

```text
start ──> library.sqlite: saved 'Library' list ──> DataFrame (window.table) ──> _track_item() per row ──> tree rows
          (first start only: empty, plus                  │                        │
           the old imported_tracks.json)                  │                        └─ KeyCalculator at slider BPM
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

1. `SONGSELECTOR_APP_DATA_DIR` environment variable (used by tests and verification)
2. The folder containing the exe (when frozen by PyInstaller)
3. `<repo>/.appdata` when running from a source checkout
4. `~/.songselector` otherwise (`~/.traktor_key_calculator` if only that one exists)

Environment variables are read through `env.getenv(NAME)`: `SONGSELECTOR_<NAME>`, else the pre-rename
`TRAKTOR_<NAME>` (fallback for one release). The ones in use: `APP_DATA_DIR`, `EMBEDDING_MODEL`,
`REKORDBOX_LIBRARY`, `CUDA_DLL_DIR`.

It holds:

| File | Content | Written |
|---|---|---|
| `SongSelector_settings.json` | UI settings. Before 1.1 it was `SpotNextTrack_settings.json`; `config.init_settings()` moves that one to the new name once and keeps it as `SpotNextTrack_settings.json.bak` | on close |
| `library.sqlite` | Collection, Song Selector rating/color, saved lists (see below) | on every change |
| `embeddings.sqlite` | CNN14 embeddings, a cache that can be deleted and recomputed (see below) | by the analysis process |
| `embeddings-laion-clap.sqlite`, `embeddings-ms-clap.sqlite` | The CLAP models' caches, same layout | by the analysis process |
| `models/cnn14.onnx` | Optional location of the embedding model. Order: model chosen in *Analysis*, this file, then `config.DEFAULT_EMBEDDING_MODEL` (`SONGSELECTOR_EMBEDDING_MODEL=none` disables the default; tests and verification do). `scripts/export_cnn14_onnx.py` creates the file from the published PANNs checkpoint | never |
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
first start, when no `Library` list exists yet, is the library empty (plus what the old
`imported_tracks.json` holds). Tracks come in by import. *Refresh* rebuilds the list from
every track in the collection table (`LibraryStore.all_tracks`) on request, and *Load CSV*
replaces it with a CSV file you pick. (Until 4.26.0 a bundled `music_test.csv` with the
developer's own 2,920 tracks was the starting library; those tracks live in `library.sqlite` now.)
SQLite was chosen after measuring on the real 5,100-track library: loading it
takes 10 ms in SQLite vs 18 ms in JSON, and updating one track 0.1 ms vs
22 ms, because JSON rewrites the whole file. Writes are transactional.

### Embedding caches and the analysis process

Every track in the library panel gets embeddings from each enabled model (`core/embedding_models.py`):
CNN14, one 2048-value vector per 5 s (background in `docs/research/audio_embeddings.md`); LAION CLAP, 512
values per 10 s; Microsoft CLAP, 1024 values per 7 s (`docs/research/text_search_clap.md`). The settings
`Embedding models` (which are analysed) and `Similarity model` (which one the map, closest matches and groups
use) are set in the *Analysis* menu.

- **One cache file per model** (`EmbeddingStore(path, spec=...)`). The embeddings table has one row per track,
  so models cannot share it without a migration; separate files also mean the CNN14 cache of earlier versions
  (`embeddings.sqlite`) is untouched and each model's cache can be deleted on its own. Map layouts live in the
  same file as their model's embeddings.
- **One process for all models.** `run_analysis(models, ...)` gets one entry per enabled model. For each job it
  checks which models lack the track (fingerprints per cache), decodes the file once (`load_audio_rates`) and
  resamples it to each of those models' rates. A model that cannot be loaded is skipped with a `warning` event;
  only when none loads is it `fatal`.
- **Every model takes raw audio.** LAION CLAP normally gets a log-mel spectrogram computed in Python
  (transformers); `scripts/export_clap_onnx.py` builds that spectrogram into the ONNX graph (DFT as two
  convolutions), checked against transformers' feature extractor to 8e-08. So `OnnxEmbedder` treats all models
  alike: windows of `chunk_samples`, padded batches of the model's batch size for the device.

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
  files are stored with `error` and retried only when the file changes (or once
  after a decoder improvement: `_FAILURES_VERSION`, kept in `PRAGMA user_version`).
  A tag edit updates the fingerprint, because the audio itself did not change.
- **Decoding** (`load_audio`): soundfile/libsndfile first (MP3, FLAC, WAV). If it cannot
  open the file (AAC: `.m4a`, `.mp4`) or stops at a damaged frame, FFmpeg through PyAV
  (`av`) is tried too and the longer result is used. A damaged file is still analysed when at
  least half of it (and 10 s) decoded, `_enough`. Both give the same audio (correlation
  0.99998 on a real track). The PyAV wheel carries FFmpeg (about 70 MB of DLLs, a GPL build:
  it includes libx264/libx265), which matters only if the exe is ever distributed.
- **Storage:** float16 + zlib, lossless; about 17–21 % of raw size, because ~87 %
  of the values are exactly 0. A 6-minute track takes ~50 KB. WAL mode lets the
  UI read while the process writes.
- **Which GPU:** DirectML gets `performance_preference=high_performance` (`DML_OPTIONS`). Without it DirectML takes
  the first adapter in Windows' per-program order, which for the packaged app on a two-GPU laptop was the integrated
  Intel UHD (python.exe got the GeForce, which hid the problem in development).
- **Parallel streams:** several analysis processes can share the job queue (`EmbeddingAnalyzer.workers`, events carry
  the worker number, crashes are attributed per worker). `auto`: the first process starts, tunes, reports `ready`;
  on a GPU a second one follows. Measured: one MS CLAP stream ~36 % GeForce load, two ~65 % at the same speed each.
- **Batch sizes are tuned** once per model, provider and onnxruntime version (`OnnxEmbedder.tune`): ms per window for
  batch 1, 2, 4, 8, 16 on synthetic audio, stopping when it gets clearly worse or memory runs out; the smallest within
  5 % of the fastest wins. Stored in `batch_sizes.json` next to the caches; the fixed table is only the fallback.
- **Device:** CUDA, then DirectML, then CPU, whichever the installed onnxruntime
  supports. The default package is `onnxruntime-directml`. Batch sizes are per model and device
  (`EmbeddingModel.batch_sizes`; CLAP on DirectML is fastest at 4, 8 overflows a 4 GB card), and batches are
  padded to a fixed shape, because GPU providers re-plan the model for every new input shape.
- **Priority:** `_lower_process_priority` sets `BELOW_NORMAL_PRIORITY_CLASS`, so the UI and Traktor go first for the
  CPU. Not Windows' background mode (`PROCESS_MODE_BACKGROUND_BEGIN`, used until 1.1.0): it also lowers memory and
  GPU scheduling priority and made Microsoft CLAP on DirectML 15x slower (36 s instead of 2.4 s per track). The
  ctypes argument types must be declared, or the 64-bit process handle is truncated and the call silently fails.
- **Groups wait for the analysis.** At startup the List's groups (Group column, group colours) are only computed
  when the similarity model has finished at least 95 % of the library (`_groups_when_ready`); otherwise the status
  line says how far it is, and the analysis progress triggers the grouping once it is up to date. Opening the map
  still arranges and groups whatever is analysed.
- **Disk writes:** the process keeps one connection (`EmbeddingStore(keep_open=True)`) with
  `synchronous=NORMAL`, so it syncs at WAL checkpoints only. UI-side stores open and close a
  connection per call, so no file stays locked.
- `launcher.py` calls `multiprocessing.freeze_support()` first and `__main__.py`
  has a `__name__` guard, because the spawned process re-imports the entry module.

### Model download

`core/model_download.py` fetches model files from the GitHub release `models-v1` (`BASE_URL`); `FILES` holds each
file's size and SHA-256. A download writes `<name>.part`, resumes it with an HTTP Range request (and starts over if
the server ignores the range), and renames it only when the hash matches; a mismatch deletes the part file, so bad
data is never resumed. `ui/model_download_dialog.py` runs it in a thread (one checkbox per model, progress, Stop)
and reports the complete models; the main window switches them on and restarts the analysis. The window is offered
once at the first start without any model, except when `SONGSELECTOR_EMBEDDING_MODEL=none` (tests, verification).
`scripts/publish_models.ps1` checks exported files against `FILES` before publishing, so the app can never download
a file it would reject.

### Free-text search

The **Sounds like** bar (main window) and the *Search by description* window share the same pieces. The bar uses
`ui/text_search_engine.py` (worker process + each model's track vectors) and shows the result as a List source of
kind `description` (`list_browser.DESCRIPTION`, an ordered kind like a playlist): `MainWindow.description_positions`
fills the # column with the ranks. Saved prompts are the setting `Saved prompts`, shared by bar and window.

*Analysis → Search by description* (`ui/text_search_dialog.py`). The prompt goes to a separate **text search
process** (`ui/text_search_worker.py` → `core.text_search.run_text_encoder`), started on the first query and
stopped when the window closes: onnxruntime must not load next to PyQt5 (see below), and each text encoder is
~500 MB, which the app only holds while searching. There, the `tokenizers` library (no transformers, no
PyTorch) turns the text into ids the way the model was trained (Microsoft: `' <|endoftext|>'` appended, padded to
77 with id 0; LAION: the text's own length), and the ONNX text encoder returns a unit vector. The window ranks
the chosen model's tracks by cosine similarity to it; a track's vector for this is the mean of its unit-length
window vectors (`clap_track_vector`). Track vectors are loaded in a thread and reloaded after new tracks are
analysed. `huggingface_hub` (a dependency of tokenizers, used only for downloads) is excluded from the exe.

### Similarity map

- **Same rows as the list.** `MainWindow._refresh_map` passes the texts of the visible
  list rows to the map (`set_tracks`), at the end of every `filter_items`, but only while the map
  tab is shown. Filters, tempo-adjusted keys and colours therefore always match the list.
- **Layout** (`build_map_data`, background thread): load all embeddings, `track_vectors`, then
  `tsne_layout` if there is no stored layout or it covers less than half of the analysed tracks.
  Otherwise `place_new` positions the new tracks. Positions are stored in `embeddings.sqlite`
  (`map_layout`) and only `save_layout` replaces them, so filtering never moves dots.
- **Reference track:** a dropped track the list does not show (e.g. on the playlist) is added to
  the map's `fields` as `reference` while it is selected (`show_reference`); its table texts come
  from `fields_provider` (`MainWindow._fields_for_key`).
- **Edges** (`SimilarityMapWidget._edges`): tracks are grouped by tempo-adjusted Camelot key,
  colour and rating, and partners are looked up per group (no all-pairs loop); one edge per
  pair, capped at `MAX_EDGES`. `_edge_sources` decides which tracks edges start from: all visible
  tracks, or the selected track plus, at half opacity, a match clicked in the list (`preview_key`).
  Per source only the `lines_per_track` partners with the highest cosine similarity are kept;
  `_add_edge_items` maps similarity within a layer to `STRENGTH_LEVELS` opacity steps.
- **Groups** (`core/clustering.py`, `SimilarityMapWidget._update_groups`): all analysed tracks are
  grouped in a thread with the chosen method; a request counter drops results of superseded
  choices. Groups only change the dot colours (`_dot_colour`), tooltips and details.
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
  only when `SONGSELECTOR_CNN14_ONNX` points at `cnn14.onnx`.
- `tests/conftest.py` makes Qt headless (`QT_QPA_PLATFORM=offscreen`) and points
  `SONGSELECTOR_APP_DATA_DIR` at a temporary folder **before** the package is imported.
- `tests/test_rename_migration.py`: settings and environment variables from before the rename
  to SongSelector keep working.
- `selfcheck.py` repeats the key scenarios inside the frozen exe, because
  PyInstaller builds can break things that pass from source (missing data files,
  hidden imports). `scripts/verify_release.ps1` runs it. With `-Model <cnn14.onnx>`,
  it also runs a real embedding analysis in the exe's analysis process.

## Packaging

**Startup splash** (`ui/splash.py`). A double-click must give feedback at once, but the one-file exe first unpacks
itself for several seconds before any Python runs. So there are two splash screens with the same image
(`ui/splash.png`, drawn by `packaging/make_splash.py`): PyInstaller's own (`Splash` in the spec, needs Tcl/Tk at build
time, so it is skipped with a warning on a Python without it) appears immediately; `app.main` then shows a Qt
`QSplashScreen`, closes the first one and keeps showing until the main window is up. `launcher.py` closes the exe's
splash at once in the embedding worker (the exe started again by multiprocessing) and in the self-check.

`packaging/SongSelector.spec` builds a one-file, windowed exe from
`packaging/launcher.py`. No data files are bundled (the former starting library CSV was removed in 4.26.0).
Large unused libraries are excluded explicitly to keep the exe size down.

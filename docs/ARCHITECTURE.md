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
| `library_store.py` | `LibraryStore`: SQLite file with the app's own collection (every track ever loaded) and the saved Library / Playlist lists |
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
| `library.sqlite` | Collection + saved lists (see below) | on every list change |
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
- `meta`: `schema_version` (currently 1). Bump it and add a migration when the
  schema changes.

On start, the window restores both lists (`_restore_lists`). Only on the very
first start, when no `Library` list exists yet, is the library built from
`data/music_test.csv` plus the old `imported_tracks.json`. After that, *Refresh*
rebuilds the list from those sources on request, and *Load CSV* replaces it.
SQLite was chosen after measuring on the real 5,100-track library: loading it
takes 10 ms in SQLite vs 18 ms in JSON, and updating one track 0.1 ms vs
22 ms, because JSON rewrites the whole file. Writes are transactional.

## External files: read-only by design

Audio files and `collection.nml` are **never written**. This is a hard rule from
the project's history (the Traktor collection is the DJ's master library). Keep
it when adding features.

## Testing

- `tests/test_imports.py`: tag parsing, key notations, collection fallback,
  relocation matching, persistence, drag-and-drop GUI flows, color painting.
  Also exports the `tagged_file()` / `make_collection()` fixtures used by other
  test modules.
- `tests/test_numeric_search.py`, `test_ratings.py`, `test_color_search.py`:
  one feature each, logic plus GUI.
- `tests/conftest.py` makes Qt headless (`QT_QPA_PLATFORM=offscreen`) and points
  `TRAKTOR_APP_DATA_DIR` at a temporary folder **before** the package is imported.
- `selfcheck.py` repeats the key scenarios inside the frozen exe, because
  PyInstaller builds can break things that pass from source (missing data files,
  hidden imports). `scripts/verify_release.ps1` runs it.

## Packaging

`packaging/TraktorKeyCalculator.spec` builds a one-file, windowed exe from
`packaging/launcher.py`. The library CSV is bundled as
`traktor_key_calculator/data/music_test.csv` inside the archive. `config.py` finds
it relative to its own `__file__`, which works both from source and frozen.
Large unused libraries are excluded explicitly to keep the exe size down.

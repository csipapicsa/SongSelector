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
| `track_import.py` | `TrackImporter` merges tag data with collection data; `merge_tracks`, `enrich_ratings`; `ImportedTrackStore` saves imports to JSON atomically |
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
data/music_test.csv ─┐
                     ├─> DataFrame (window.table) ──> _track_item() per row ──> tree rows
imported_tracks.json ┘                                  │
                                                        └─ KeyCalculator at slider BPM
Dropped audio file ──> TrackImporter.read()
                         ├─ tags (mutagen)
                         └─ fallback: TraktorCollection.find()  (key, BPM, color, rating)
                       ──> merge_tracks() into window.table ──> ImportedTrackStore.save()
```

- **Library CSV columns** used: `Artist, Title, File_Path, Comment, BPM, Color,
  Musical_Key_Base, BaseMinorOrMajor, Genre`, plus optional `Album, Rating`.
  Imported rows also carry `Key_Source`, `BPM_Source`, `Color_Source` (shown as
  row tooltips) and `Imported`.
- **Moving the slider** re-runs `_track_item()` for all rows. Nothing is cached
  per tempo.
- **Duplicates:** rows are matched by `canonical_path()` (normalised, case-folded
  Windows path). Dropping a file again updates its row instead of adding one.

## Persistence

`config.APP_DATA_DIR` resolves to (first match wins):

1. `TRAKTOR_APP_DATA_DIR` environment variable (used by tests and verification)
2. The folder containing the exe (when frozen by PyInstaller)
3. `<repo>/.appdata` when running from a source checkout
4. `~/.traktor_key_calculator` otherwise

It holds `SpotNextTrack_settings.json` (the name is historical and kept for
compatibility with existing installs) and `imported_tracks.json`. Settings are
written in `closeEvent`.

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

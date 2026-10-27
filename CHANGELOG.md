# Changelog

Versions before 4.5.0 were not tagged in git. They are reconstructed from the
build history (see `docs/history/`). Earlier exe names are given so old copies
can be identified.

## [4.8.0] - 2026-10-27

- **Multi-selection** in both panels: Shift+click (range) and Ctrl+click (toggle).
  Dragging takes all selected files; rating and color apply to every selected row.
- **Delete key / right-click → Remove from library|playlist** removes the selected rows from
  that list. The library asks first. Tracks stay in the collection (with ratings and
  embeddings), and files on disk are never deleted. Removed playlist tracks reappear in the library.
- **Comment** can be edited too (*Edit track info…*): written as the file's main comment
  (ID3 `COMM`, Vorbis `comment`); other comment-type frames such as iTunes' `iTunNORM` are kept.
- Fix: a file without a main comment no longer shows another comment-type frame
  (e.g. `iTunNORM` loudness data) in the Comment column.
- The embedding model of the DJ mix segmentation project
  (`E:\GITHUB_E\MusicFindBoundaries\cnn14.onnx`) is the default, so analysis starts
  without choosing a file. *Analysis → Choose embedding model…* still overrides it.

## [4.7.0] - 2026-10-27

- **Own rating and color.** New columns *Rating - Song Selector* (1–5) and *Color - Song
  Selector* (Traktor's 9 color names), set by right-clicking a row in either panel. They are
  stored in `library.sqlite` (schema 2, existing files are upgraded in place) and never
  overwritten by Traktor, file tags, Refresh or Load CSV. They can be searched, sorted,
  filtered in Advanced Search (numeric comparisons, color names), and typed as
  `sscolor:blue` in the search bar.
- **Edit Artist / Title / Genre** (right-click → *Edit Artist / Title / Genre…*). The
  change is written into the audio file's tags (MP3, WAV, FLAC), keeping all other tags
  and the ID3 version. This is the first time the app writes to audio files. The
  Traktor collection stays read-only.
- **Background audio embeddings.** PANNs CNN14 (same model and preprocessing as the DJ mix
  segmentation project; verified identical) computes one 2048-value vector per 5 s for
  every library track. Runs in a separate low-priority process; the app stays usable,
  progress shows in the status bar, and *Analysis* pauses it or chooses the model file.
  Stored losslessly compressed in `embeddings.sqlite` (~50 KB per 6-minute track).
  Uses an NVIDIA GPU when `onnxruntime-gpu` is installed (~4x faster), otherwise the CPU.
- New dependencies: onnxruntime, soundfile, soxr. The exe grows from 59 to 74 MB; the
  327 MB model is not bundled.
- Build: `scripts/update_qt_msvc_runtime.ps1` replaces PyQt5's outdated MSVC runtime,
  which made onnxruntime crash.

## [4.6.0] - 2026-10-27

- **Library and playlist are remembered.** New `library.sqlite` next to the settings
  holds the app's own collection (every track ever loaded) and the saved Library
  (right) and Playlist (left) lists. Both panels are restored on start.
- First start migrates `imported_tracks.json` into the collection. The JSON file is
  left untouched as a backup and is no longer written.
- **Right-click → Delete duplicates from the list** in the library panel removes rows
  with the same file path (case- and slash-insensitive), keeping the first.
  Only the list changes; files on disk are never deleted.
- Where a path occurs more than once, the first row is now used consistently
  (previously the last row won when adding to the playlist).
- Refresh and Load CSV tooltips explain that they rebuild or replace the library list.

## [4.5.0] - 2026-10-27

Repository set up as a maintained project. App behavior is identical to the
2026-10-13 `TraktorKeyCalculator_ColorSearch_Ratings.exe`.

- Code organised into a package (`traktor_key_calculator.core` / `.ui`);
  modules renamed: `functions_app` → `audio_metadata`, `constants_file` → `key_tables`,
  `key_functions` → `key_calculator`, `advanced_search_panel` → `advanced_search_dialog`,
  `main` → `app`, `verify_app` → `selfcheck`.
- Running from source now stores data in `<repo>/.appdata` instead of the source folder.
- Pinned dependencies, pytest configuration, and repo-relative build and verify scripts.
- Exe is now named `TraktorKeyCalculator-<version>.exe`.

## Feature history (built 2026-10-13, on top of the stable v4 source)

| Version | Former exe name | Added |
|---|---|---|
| 4.5 | `TraktorKeyCalculator_ColorSearch_Ratings.exe` | Named color search (`color:blue`, `-color:red`, `color:none`), Colors dropdown, color names in Complex Search |
| 4.4 | `..._DragDrop_Colors_Search_Ratings.exe` | Rating (1–5) visible and searchable in both panels; missing ratings filled from Traktor |
| 4.3 | `..._DragDrop_Colors_Search.exe` | Numeric Complex Search: >, <, >=, <=, decimal values |
| 4.2 | `..._DragDrop_Colors.exe` | Colors in both panels, working Color by Key, Traktor category colors |
| 4.1 | `TraktorKeyCalculator_DragDrop.exe` | Working drag and drop import, tag reading, Traktor fallback, duplicate handling, saved imports |
| 4.0 | `TraktorKeyCalculator.exe` (rebuilt) | Stable v4 baseline (`version4_20251104`, November 2025) |
| 1–3 | `TraktorKeyCalculator_v1/v2/v3.exe` | Early CSV-based versions (Tkinter in v1; playlists in v3) |

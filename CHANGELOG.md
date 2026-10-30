# Changelog

Versions before 4.5.0 were not tagged in git. They are reconstructed from the
build history (see `docs/history/`). Earlier exe names are given so old copies
can be identified.

## [4.20.0] - 2026-10-30

- **Complex Search: column *None* switches a row off.** The column list of each row now starts
  with *None*. A row set to *None* keeps its condition and value (also after restarting) but is
  left out of the search, the *Advanced Search (n active)* count and the input checks, so a rule
  can be paused and brought back by picking its column again. New rows still start on the first
  real column.

## [4.19.1] - 2026-10-29

- **3D view: dots get smaller with distance** (half size at the back, 1.6 times at the front), as
  well as fading, so the depth reads at a glance. The 2D map keeps one size.

## [4.19.0] - 2026-10-29

- **Changes made in Traktor come in by themselves.** The app watches Traktor's `collection.nml`;
  after Traktor saves it (mostly when Traktor closes), it is read again in a low-priority
  background thread and all changes are applied at once: list, playlist and `library.sqlite`,
  with a status message such as *Updated from Traktor: 12 tracks (BPM 3, colour 8, rating 2)*.
  Changes made while the app was closed come in a few seconds after it starts.
  - Only what changed **in Traktor** since the last sync is taken (key, BPM, colour, rating, also
    a cleared colour or rating), so a rating or key read from a file's tags is not overwritten by
    an old Traktor value. The first sync takes Traktor's colours and fills empty keys, BPMs and
    ratings.
  - *Refresh* and *Load CSV* rebuild the list from the CSV as before; imported tracks keep the
    synced values, CSV rows get them again when Traktor next changes them.
- **Sorting the list no longer freezes the window.** With a row selected, a click on a column
  header took about 15 s for 3,600 tracks (the rows were taken out and put back one by one; Qt
  re-laid out the view each time). Qt now sorts in place: 0.1 s. Numbers still sort as numbers,
  keys by Camelot number, empty and *Unknown* values last.
- **Curved edges on the similarity map:** each edge is a gentle arc, so the edges of a track fan
  out instead of crossing as straight spokes. *Edges → Curved lines* switches back to straight.
- **3D view** (*3D* button next to *Fit*): the tracks are arranged in three dimensions, Shift+drag
  rotates, scroll zooms, drag moves. Far dots fade, near ones lie on top; edges, glows, cards and
  Ctrl+click compare work as in 2D. The first 3D arrangement takes a few minutes in the
  background (about 3 minutes for 3,500 tracks), then it is cached like the 2D map.

## [4.18.0] - 2026-10-29

- **Ctrl+click a dot on the similarity map to compare it with the selected track.** The selected
  (base) track stays selected; the clicked one glows magenta, gets a dashed line to the base in the
  colour of their harmonic mix, and a card with its details, the mix (*Perfect mix*, *+1 mix*, ...)
  and the similarity score. Its row in the closest matches is marked. Ctrl+click it again to end
  the comparison; a plain click still selects. Clicking a closest match shows the same card.
- **Hovering a dot shows a card** instead of the yellow tooltip: artist - title, key and BPM now,
  the mix and similarity to the selected track, and the hover fields with colours as coloured dots
  and ratings as stars.
- **Colours are shown as a coloured dot and name** (● Orange) in the map details instead of the
  number.
- Tooltips everywhere use the theme's colours instead of the yellow Windows default.

## [4.17.0] - 2026-10-29

- **Fix: empty, nameless gaps between playlist columns** (since 4.15.0). Every hidden column (e.g.
  Original BPM, Path) still took about 100 px of blank space. The resize mode was set after the
  columns were hidden, which Qt answers by keeping their old width; it is now set first.
- **Track counts:** next to the *List* / *Similarity map* tabs, e.g. *1,234 of 3,651 tracks, 3
  selected* (after search and filters); under the playlist, e.g. *28 tracks, 2 selected*.
- **Ratings as stars** (★★★★☆) in both lists, the closest matches and the map details. The cell still
  holds the number, so sorting, search (`5`) and Advanced Search work as before; 0 (unrated) is blank.
- **Closest matches on the map:**
  - *List the 50 closest* (adjustable, 5-2,000; was a fixed 15). The 15 most similar keep their ring
    on the map, so the map is not covered with rings.
  - Right-click the header to choose its columns: any library column (BPM, keys, genre, comment,
    colours as dots, ratings as stars, ...) next to Similarity and Mix. Remembered; numbers sort as
    numbers.

## [4.16.1] - 2026-10-28

- **Fix: the closest-matches panel disappeared on narrower windows** (since 4.15.0). The longer
  caption above the matches and the one-line status under the map set the map's minimum width; the
  map then grew wider than the window and the splitter collapsed the panel to nothing. The caption
  and status now wrap, the panel cannot collapse (at least 220 px), and its width is remembered.

## [4.16.0] - 2026-10-28

- **Fewer, graded edge lines on the similarity map.** Edges from a track go only to the partners
  that sound most similar (*to the 20 most similar*, adjustable next to *Edges*); the more similar,
  the more opaque the line (the weakest at 15 %). Before, every harmonic / same-rating partner got a
  line, hundreds for one track.
- **The selected track glows white** (pulsing), like the magenta glow of a clicked match.
- **Groups:** a new row colours the dots by unsupervised groups instead of the Traktor colour, to
  compare three methods, each with one parameter: *k-means* (number of groups), *Neighbour
  communities* (resolution) and *Map density* (dense %; thin areas stay dark grey). The summary shows
  the number of groups and the largest; hover and the details box show a track's group. About a
  second for 3,500 tracks, in the background. On the developer's library the groups match the
  style (DnB / breaks / house) 75-83 % of the time, against 47 % for one group.

## [4.15.0] - 2026-10-28

- **Playlist columns can be resized again.** They were all set to stretch, which blocks resizing by
  hand; their widths were also never restored, because they were saved as *Column sizes left* and
  read back as *Column Sizes left*.
- **Similarity map, closest matches:**
  - Clicking a match makes it stand out on the map: a pulsing magenta glow and a thick ring (magenta
    because no Traktor colour is), and its harmonic edges drawn at half opacity next to the selected
    track's edges. The selection stays. Double-click selects the match (it no longer adds it to the
    playlist; drag it there instead).
  - Matches already on the playlist are shown in italics.
  - *Harmonic only* keeps tracks without a key in Traktor (Mix: *no key*): their sound can still
    match, and the embeddings do not need Traktor's analysis. Before, they were dropped, and a selected
    track without a key had an empty list.

## [4.14.0] - 2026-10-27

- **Playlist tracks stay in the library list**, dimmed and in italics, so a search finds them.
  Previously they were hidden without notice, so a search for an artist could miss a track that
  was on the playlist. *View → Hide playlist tracks in the library* restores the old
  set-building behaviour; the status bar then says how many matches are hidden.
- **Active Advanced Search is visible:** the button reads e.g. *Advanced Search (2 active)*,
  highlighted, with the filters in its tooltip, and the status bar says *Advanced Search is on*.

## [4.13.0] - 2026-10-27

- **Drop a track on the similarity map to select it**, e.g. from the playlist. A track the list
  does not show (a playlist track, or one filtered out) appears as a reference dot with label and
  details; its closest matches come from the list. Selecting another dot removes the reference.
  Tracks that are not analysed yet are reported in the status line.

## [4.12.0] - 2026-10-27

- **Folders can be dropped** on the library or playlist (or the window): all MP3, WAV and FLAC files
  in them and in all subfolders are imported, in folder/name order. *Import → Add folder (with
  subfolders)…* does the same. Imports of more than 25 files show a progress dialog with Cancel.
- **Similarity map, after first use:**
  - The selected track shows a label next to its dot (artist – title, key at master tempo, BPM) and a
    details box above the closest matches.
  - Clicking a closest match no longer changes the selection: it rings the match in orange and
    scrolls it into view.
  - Drag a dot, or one or more closest matches, straight into Traktor (or Explorer, or the playlist).
  - Closest-match columns sort on click (ascending/descending): similarity as a number, mix by
    strength, names case-insensitively. The chosen order is kept for the next track.
  - Fix: "Showing the first 2500 edges" stayed visible after switching back to edges from the
    selected track only.
  - Colour 0 ("no colour") is no longer listed in hover and details.

## [4.11.0] - 2026-10-27

- **Similarity map** (library panel tab *Similarity map*, Ctrl+2; *List* is Ctrl+1). Every analysed
  track of the current (filtered) list is a dot; similar-sounding tracks lie close together.
  Dot colour: Song Selector colour first, then Traktor's. Filtering hides dots but never moves the
  rest. Scroll to zoom, drag to pan, hover for details (*View → Map hover details…*), click for the
  15 exact closest matches (ringed on the map, listed with similarity and mix type), double-click to
  add to the playlist, right-click for the usual track menu.
- **Edges** (*Edges* menu): harmonic mixes on the tempo-adjusted Camelot key (perfect, ±1, scale
  change, energy boost, mood shifter, Jaw's, diagonal), same colour, same rating. They start at the
  selected track, or optionally connect all visible tracks (capped at 2,500).
- **Harmonic mixing calculator** (`core/harmonic.py`) ported from the master thesis project and
  tested against every cell of Mixed In Key's table (24 keys × 8 mixes).
- Map layout: t-SNE in numpy (no new dependency), computed in the background and cached in
  `embeddings.sqlite`; tracks analysed later are placed next to their closest matches instantly.
  *Re-arrange map* recomputes it.

## [4.10.0] - 2026-10-27

- **Dark grey theme** (Qt Fusion style), default; *View → Dark theme* switches to light while
  the app runs. Row tints adapt to the background.
- Status messages use one set of theme-aware colours (info / ok / warning / error) instead of
  hard-coded black, green and red, which were unreadable on dark backgrounds.

## [4.9.0] - 2026-10-27

- **Embeddings on the GPU in the exe** through DirectML (`onnxruntime-directml`): works on any
  DirectX 12 GPU, falls back to the CPU. GTX 1650 Ti: 0.58 s instead of 5.5 s model time per
  6-minute track (same speed as CUDA, but no CUDA install and +10 MB instead of +1 GB).
  Batch size per device (DirectML 8, CUDA 16, CPU 1), with fixed-shape padded batches.
- **Fix: the analysis process really runs at low priority now**: below-normal CPU and very low
  disk I/O (Windows background mode). The earlier priority call silently failed, because a
  64-bit handle was passed as a 32-bit integer.
- **Fewer disk writes:** the analysis process keeps one database connection with
  `synchronous=NORMAL` (syncs only at checkpoints), and `library.sqlite` no longer rewrites its
  schema version on every connection. This matters on slow SATA SSDs, where a stalled disk made
  playback stutter in other programs.
- **Right-click → Remove missing files from the list** (library asks first, playlist does not).
- Build intermediates and release verification now use the system temp folder instead of the
  project disk; the verification window wait is 60 s.

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

# Changelog

This project follows [Semantic Versioning](https://semver.org/).

**About the version numbers.** SongSelector grew out of an earlier personal tool, the Traktor
Key Calculator, whose builds were numbered v1–v4. Development continued on that numbering, so the
builds below are called 4.5.0–4.26.0. With the first public release, SongSelector starts its own
version line at **1.0.0**. The 4.x entries are kept unchanged as pre-1.0 history; commit messages
from that period still mention 4.x numbers.

## [Unreleased]

- **The model download works again.** *Analysis → Get models…* → *Download* fetches CNN14 and both CLAP models
  (resumable, checksum-checked) from Hugging Face, one repo per model, each with a model card naming the source,
  the changes and the licence: [`songselector-cnn14`](https://huggingface.co/csipapicsa/songselector-cnn14),
  [`songselector-clap-laion`](https://huggingface.co/csipapicsa/songselector-clap-laion),
  [`songselector-clap-ms`](https://huggingface.co/csipapicsa/songselector-clap-ms). The app downloads from a fixed
  commit of each, so what a version gets never changes. In 1.2.0 the window could only explain how to build them.
  `scripts/publish_models.py` (replaces `publish_models.ps1`) checks and uploads a new export.
- **Choose the models folder.** *Get models…* → *Models folder…* (also in the *Analysis* menu) replaces *Open models
  folder*, which only opened it: pick any folder, e.g. one that already holds the model files or is shared by several
  installations. The app reads the models from it and downloads into it; the window shows at once what is installed
  there.
- **New tagline on the startup screen:** "Track organizer for DJs and music collectors" (was "Harmonic keys and
  audio similarity for DJs"); the app is useful beyond DJing too.
- **A compact top: two rows instead of five.** *Master tempo* is a box at the start of the search row: the arrows or
  the mouse wheel move it 1 BPM, or type a number and press Enter (the slider row is gone). Gone too: *Refresh*,
  *Load CSV*, *Show all tracks* (Browser → *All Tracks* does it) and *Add Selected to Playlist* (now in the List's
  right-click menu as *Add to Playlist*; dragging works as before).
- **One Model box for the search and the map.** The *Model* box next to *Describe a sound* now also sets the model
  of the similarity map, its closest matches and groups (the same as *Analysis → Similarity model*). It lists every
  model whose files are there; CNN14 has no text side, so with CNN14 the description field says to pick a CLAP
  model.
- **The map moves freely.** Drag it anywhere, even fully out of view (until now it could hardly move, and not at all
  once zoomed out, so a hover card at the edge stayed cut off); *Fit* brings it back. No scroll bars any more.
- **Similarity map: one tidy toolbar.** The controls are in one row, ordered by task: *Map the List only*, *Groups*,
  *Edges* (now one menu with every edge setting: relations, how many partners, between all tracks, curved), then
  *3D*, *Fit*, *Re-arrange map*. What does not fit folds into a » menu, so the map no longer forces the window to
  ~1,700 px. The closest-matches filter moved next to the list it filters ("List the 50 closest | of all tracks");
  the how-to text moved behind a **?** at the end of the status line.
- **The map has no own window any more.** *Own window* (1.2.0) is gone; a map left in its own window opens in its
  tab again.
- **Map info boxes stay narrow.** The hover card, the compared track's card and the selected track's label wrap
  their text at 360 px (*View → Map track details…*, from 200 px), so a long file name no longer makes a box as wide
  as the map and hides the dots under it; words without spaces break where needed. Short text keeps its own width.
- **Time left of the embedding analysis.** The progress line says how long the analysis will still take
  ("Embeddings (CNN14+LAION CLAP, CPU): 5/200, about 39 min left - track.mp3"), from the speed of the last few
  minutes, once a few tracks have been analysed.
- **Turn the 2D map.** Shift+right-drag turns the similarity map left or right about the middle of the view; the
  angle is kept. Shift+drag still rotates the 3D view.
- **Choose every detail the map shows, and where.** *View → Map track details…* (was *Map hover details…*) is a grid
  with a column each for the hover card, the selected track's label and the details panel: the cover, *Artist -
  Title*, the key at master tempo and BPM, the mix and similarity to the selected track (cards), the group, and
  every List column can be switched on or off in each. Before, only the columns could be chosen (for the card and
  the panel together) and the rest was always shown. Columns chosen before carry over.
- **Hide the selected track's details beside the map.** Right-click anywhere beside the map, or *View → Selected
  track details*, shows or hides the details above the closest matches; the list gets their room.
- **The map's buttons are below the map**, so the map starts right under the tabs.
- **Fold the search rows away.** *View → Search bars*, or dragging the line under them up (as the Playlist and
  Browser fold away on the left), hides *Master tempo*, *Search* and *Describe a sound*; a search set before stays
  in force.

## [1.2.0] - 2026-11-17

1.1.4 was never released; its changes ship in 1.2.0 together with the items below.

- **"Map the List only" follows the List.** The button (formerly *Only listed tracks*) maps and groups just the
  tracks the List shows, and now keeps doing so: a new description search, a switch between the CLAP models, a
  changed *Top* number or filter maps the new List after a short pause. Before, the map kept the List from the
  moment the button was pressed, so after a new search it showed only the tracks that were in both the old and
  the new List. *Re-arrange map* still arranges the List again from scratch.
- **Traktor's smartlists work.** Under *Traktor Playlists* in the Browser, a smartlist now shows its tracks like a
  playlist (and can be loaded into the Playlist tab or copied). Its query is evaluated on Traktor's own collection:
  BPM, colour, rating, genre, comment, artist, title, file path, key (Open Key, e.g. `1m`), length, play count and
  import date (`MONTHS_AGO(1)`), with `== <> < <= > >= % !% ~`, `&` and `|`. Two assumptions: `~` means within 1 BPM,
  and `&` binds tighter than `|`. A smartlist on *played in this session* cannot be evaluated outside Traktor; the bar
  above the List says so.
- **Speed change column.** How much faster (+) or slower (-) each track plays at the master tempo, in percent with
  one decimal (`+6.2%`, `-13.0%`), next to *Original BPM*; it follows the tempo slider and sorts as a number.
- **Advanced Search on the speed change.** *Speed change* is an Advanced Search column with two extra conditions:
  *within ± (%)* (e.g. 8: tracks that need at most 8 % faster or slower at the master tempo) and *outside ± (%)*;
  the usual comparisons work on the signed value. Smartlists with such a rule follow the master tempo.
- **Sorting by Group sorts by Match within each group** (the best match of a description search first), in both
  directions.
- **View -> Always on top** keeps SongSelector (and the map in its own window) above every other window, e.g. above
  Traktor. Remembered.
- The map's labels and cards no longer show " - Title" for tracks without an artist.
- **Group numbers follow the map.** Groups are numbered along a path through the map, so groups next to each other
  get numbers next to each other (before: by size, so neighbours could be 3 and 14). The colours repeat after the
  palette instead of making later groups grey.
- **Describe a sound searches the shown playlist or smartlist.** With a playlist, smartlist or other Browser entry
  in the List, the description search now ranks only its tracks (before: the whole library) and the entry stays
  selected in the Browser; a new prompt, another model or *Top* keep it, and clearing the search shows the entry
  again. The status line says "... within Smartlist: ...".
- The List's *Group colours* switch is now called **Cluster group colours**.
- **Cover art in the List and the Playlist.** *View -> Cover art*: a *Cover* column (after `#`) with each track's
  picture: the one embedded in the file, else `cover.jpg` / `folder.jpg` next to it. Two styles: *cropped to the row
  height* (normal rows, the top of the picture) or *square rows* (every row as tall as the picture, also those
  without one), in 48, 72 or 96 px. Off by default. Covers load in the background, only for the rows you see, and
  are kept as small thumbnails in a `covers` folder next to the library, so they are read from the files once.
  The map shows them too: in the hover and comparison cards, the selected track's details, and in a Cover column
  of the closest matches.
- **The map in its own window.** *Own window* on the map moves it into a separate window (another screen, any
  size); it keeps following the List, and Ctrl+2 brings it to the front. Close that window (or *Back to the tab*)
  to get it back in its tab. Its size and position, and whether it was in its own window, are remembered.
- **Delete duplicates, three ways.** *Right-click -> Delete duplicates from the list* now offers *Same file path*
  (as before), *Same Artist - Title* (case and spaces ignored) and *Same file* (a copy in another folder: same size
  and content). It first shows each group and which row stays: the one whose file exists, then the one with the most
  information (comment, colour, rating, key, BPM...), then the one in the Traktor / Rekordbox collection, then the
  first. Untick a row to keep it too. Only list rows are removed, never files.
- **Models: no broken download.** *Analysis -> Download models...* fetched from a model release that was never
  published, so it failed with "404 Not Found". The model weights are not redistributed, so the window is now
  *Analysis -> Get models...*: it shows which models are installed, explains how to build the others with the
  export scripts, and opens the models folder. (A `Model download URL` setting re-enables downloading from your own
  server.)
- **Saving the library writes only what changed.** Every save (an import, a removal, a refresh) used to rewrite
  all tracks and the whole list order of `library.sqlite`. Now unchanged tracks and list positions are not written
  at all, and the file uses SQLite's WAL journal (fewer disk syncs; still one file between saves). On a 3,400-track
  library on a SATA SSD under load: 0.13 s instead of 2.5-5.5 s per save.
- **Importing or removing a few tracks no longer rebuilds the List.** Only their rows are added, redrawn or taken
  out: importing one file takes about 0.7 s instead of 2 s on the same library.
- **Playlist tracks on the map.** Tracks selected in the Playlist get an amber ring on the map. If the List
  filters them out, they are shown anyway (paler, dashed ring) without changing the List's closest matches or
  edges; click one to see its closest matches in the List. With *Map the List only*, a selected Playlist track is
  placed next to its most similar tracks (no new arrangement).
- **A spinner shows when something is working.** A small turning arc next to the status line while a file is
  saved or a description search runs, next to the analysis progress while tracks are analysed, and next to the
  map's status while the map is arranged or grouped. Its tooltip says what is running.
- **Editing a track's tags no longer freezes the app.** *Edit track info* used to save the whole library for one
  changed track, on the window's own thread: 2.5 s on the library's SSD, 4-5 s and more while the analysis kept the
  disk busy. The file is now written in the background, only the changed track is saved, and the window keeps
  working (longest pause under 0.1 s in the same test). The status line says "Saving..." until it is done.
- **A tag edit no longer makes the CLAP models analyse the track again.** Only CNN14's analysis was marked as
  still current after a tag-only change; LAION and Microsoft CLAP saw a changed file and analysed it again.
- *Edit track info*: the file path can be selected and copied.
- **Closest matches can follow the Edges menu.** The *harmonic only* checkbox is now a choice: *all*, *harmonic
  only*, or *Edges selection*, which lists only tracks with a relation checked under *Edges* (mix types, same
  colour, same rating) and updates when the menu changes. A saved *harmonic only* carries over.
- **Ending a comparison is easier.** Esc first ends the comparison (the Ctrl+clicked dot or clicked match) and
  keeps the selected track; a second Esc clears the selection. Ctrl+click on empty map space also ends it.
- **Labels and cards no longer cover each other.** The selected track's label, the comparison card and the hover
  card each move to a free corner of their dot (and stay inside the map if they can), also after zooming.
- The tooltips of the map's edge settings explain that "to the N most similar" is relative: every track keeps its
  N most similar partners among the tracks on the map.

### From 1.1.4 (unreleased, 2026-11-16)

- **Top N updates the List right away.** Changing the number next to the description field now shows the new
  number of tracks immediately. The whole ranking of the last search is kept, so no new search is needed. The
  field takes any number (up to 100,000) or **All** (one step below 1, or type it), which lists every analysed
  track, ranked. "Top" is now a label next to the field, which shows just the number.
- **Match column.** While the List shows description results, *Match* shows how well each track matches the
  description, as a percentage: the cosine similarity of the description and the track in the CLAP model x 100
  (higher is closer). For music it is mostly 10-50 %; it is not a probability, so compare tracks within one search
  rather than between searches or models. The status line shows the range of the shown tracks. The column sits next to `#` in
  the List and is hidden in the Playlist (*right-click a column header* to show or hide it).

## [1.1.3] - 2026-11-16

- **Choosing a model analyses what it is missing.** Switching the description search between LAION CLAP and
  Microsoft CLAP (or choosing a *Similarity model*) now checks how many library tracks that model has analysed. If
  some are missing, the model is switched on under *Analysis -> Embedding models* and analyses them in the
  background; the status line says how many it has and how many are coming. At startup the app checks each model's
  coverage the same way, and the models in use fill their gaps.
- **Each model's coverage at a glance.** *Embedding models* and *Similarity model* show "N of M tracks" per model,
  and the tooltip of the analysis progress lists all models. When the analysis finishes but a model is still short
  (e.g. it could not be loaded), the progress says so instead of "up to date". Counts include only tracks that are
  in the library.
- **The window no longer stretches.** A long status message, file name or saved prompt raised the window's minimum
  width, so the window grew and could not be made narrower again. Long texts are now shortened with "..." (the whole
  text is in the tooltip), and the description field no longer grows with the longest saved prompt.
- **"Sounds like:" is now "Describe a sound:"**, with a hint that it takes free text (AI search with the CLAP
  models). The dropdown's first entry, *no search: show all tracks*, clears the search and shows all tracks again;
  Enter in an empty field does the same.

## [1.1.2] - 2026-11-13

- **The analysis now uses the graphics card it should.** On laptops with two GPUs, DirectML picked the integrated one
  for the packaged app (Intel UHD), so the GeForce stayed idle. It now asks for the high-performance GPU: Microsoft
  CLAP 42 ms per window on the GeForce GTX 1650 Ti instead of about 60-250 ms on the Intel graphics.
- **Two analysis streams on a GPU.** One stream kept the GPU only about a third busy; two nearly double the speed at
  about two thirds load, leaving headroom for Traktor and the rest of the system. *Analysis -> Parallel analysis*:
  Automatic (2 on a GPU, 1 on the CPU), or 1-3 streams.
- **Batch sizes measured on your machine.** Each model's best batch size is measured once on the GPU (a few seconds,
  the first time) and remembered in `batch_sizes.json` next to the caches, instead of a fixed table from one laptop.
- **"Sounds like:" bar** above the List: type a description or pick a saved prompt from its dropdown, press Enter, and
  the List shows the closest tracks, best first in the # column (keys at master tempo, colours, drag to Traktor as
  usual). The star saves the prompt, the cross deletes it; Top N sets how many. "Show all tracks" goes back. The
  *Search by description* window is still in the Analysis menu.
- **Esc on the similarity map** clears the selection: no selected or compared track, no rings, edges, closest
  matches or card.

## [1.1.1] - 2026-11-13

- **Embedding analysis up to 15x faster on the GPU.** The analysis process ran in Windows' background mode, which
  also lowers memory and GPU scheduling priority: Microsoft CLAP on DirectML took 36 s per 6-minute track instead of
  2.4 s (model loading 20 s instead of 1 s). It now only gets below-normal CPU priority, so the UI and Traktor still
  go first for the CPU.
- **Groups wait for the analysis.** At startup the List's groups were computed from whatever the similarity model
  had analysed, even 1 track of 3,700, while the analysis was still running. Now they are computed once the model
  has finished at least 95 % of the library; until then the status line says how far it is, and grouping starts by
  itself when the analysis is up to date. Opening the map still groups what is there.

## [1.1.0] - 2026-11-13

- **Two more embedding models: LAION CLAP and Microsoft CLAP**, next to CNN14. CLAP models put sound and text in
  one space. *Analysis → Embedding models* chooses which ones are kept up to date; *Analysis → Similarity model*
  chooses which one the map, the closest matches and the groups use (each keeps its own map layout). One
  background process analyses all of them, decoding each file once and resampling it per model; each model has
  its own cache file (`embeddings-laion-clap.sqlite`, `embeddings-ms-clap.sqlite`), and the CNN14 cache of
  earlier versions is untouched.
- **Search by description** (*Analysis → Search by description...*, Ctrl+Shift+F): type what a track should sound
  like ("funky breakbeat with a groovy bassline") and get the closest tracks of a CLAP model, with saved prompts,
  double-click to select a result in the List, and drag results onto Traktor. The text encoder runs in its own
  process, started on the first search and stopped when the window closes.
- **`scripts/export_clap_onnx.py`** builds the CLAP model files from the published weights and checks each one
  against PyTorch before writing it (largest difference 1e-6 or less). LAION's spectrogram is built into the
  audio model, so every model takes raw audio. Two exporter problems found and fixed on the way: msclap's audio
  encoder froze the batch size into the graph (cosine 0.62 at batch 3), and transformers' attention masks could
  not be traced.
- **Download models from the app** (*Analysis → Download models...*; offered once at the first start without any
  model): the files come from the project's `models-v1` GitHub release, resume after an interruption and are
  only used once their SHA-256 matches the app's list. Downloaded models are switched on and analysing starts.
  `scripts/publish_models.ps1` checks exported files against that list and publishes the release (with the
  sources and the licence texts: CC BY 4.0, Apache 2.0, MS-PL).
- Batch sizes per model: CLAP on DirectML is fastest at 4 windows per call (55-62 ms per window on a GTX 1650 Ti).
- New dependency: `tokenizers` (Hugging Face's tokenizer library); its download-only dependencies are kept out of
  the exe. The exe's self-check now also starts the text search process.
- **Startup splash screen.** Double-clicking the exe shows the SongSelector image straight away, with a status line,
  until the window is up. Before, nothing happened for several seconds. The exe's own splash (PyInstaller) covers the
  unpacking of the one-file exe; the app then shows the same image while it loads the library, and closes it when
  the window appears. The background analysis process never shows it. The exe's splash needs Tcl/Tk in the build
  Python: release builds have it; a local build without it prints a warning and keeps only the app's splash.
- Measured while doing this (3,753 tracks): about 3 s from Python's start to the window, plus 4-5 s of unpacking
  in the one-file exe. Embeddings are not read at startup.
- **Renamed to SongSelector everywhere:** the exe is now `SongSelector-<version>.exe`, the Python package
  `songselector` (`python -m songselector`), the main window class `MainWindow`. Names that refer to
  Native Instruments' Traktor (the Traktor collection, *Traktor Playlists*) stay.
- **Settings file renamed** to `SongSelector_settings.json`. On the first start an existing
  `SpotNextTrack_settings.json` is moved to the new name and kept as `SpotNextTrack_settings.json.bak`;
  this happens once, so resetting the settings later does not bring the old ones back. Tested.
- **Environment variables** are now `SONGSELECTOR_*` (`SONGSELECTOR_APP_DATA_DIR`, `_EMBEDDING_MODEL`,
  `_REKORDBOX_LIBRARY`, `_CUDA_DLL_DIR`). The old `TRAKTOR_*` names are still read as a fallback until 1.2.
- **New `scripts/export_cnn14_onnx.py`:** builds `cnn14.onnx` from the published PANNs checkpoint
  (SHA-256 checked) and compares it with PyTorch. Until now the model could only come from the developer's
  machine. Checked: on DirectML its embeddings are identical (difference 0.0) to the model the app used so far.
- README rewritten for people new to the project: what the app does, how it is built and tested, how to
  install it and get the model.
- Backlog updated (rename, linter, CI and real-file tests were done); dead `test = 100` removed from `config.py`.

## [1.0.1] - 2026-11-05

Development only; the app behaves the same.

- **Lint gate:** ruff (pinned, rules listed in `pyproject.toml`) runs on every pull request next to the
  tests; `main` only accepts pull requests whose checks pass. Replaces pyflakes.
- Existing findings fixed (139 → 0). Two were real: a test helper defined twice in the same class, so
  the stricter `wait_for_map` (which also waits for a pending reload) was never used; and the module
  docstring of `config.py` sat after the imports, so Python did not treat it as the docstring.
- **Security checks in CI:** gitleaks scans the whole git history for secrets (checksum-verified download,
  findings redacted in the public logs), and pip-audit checks every dependency against known
  vulnerabilities. CI also runs weekly, so a newly published vulnerability is noticed without a code change.
- Tests that need the developer's real library are marked `local_data` and deselected in CI, instead of
  skipping silently; `--strict-markers` turns a mistyped marker into an error. CI badge in the README.
- **Automated releases:** pushing a version tag (`v1.2.3`) builds the exe on GitHub, verifies it (the
  packaged self-check and a real window) and publishes a GitHub Release with the exe, its SHA-256
  checksum and this changelog's section as notes. The tag must match the version in the code and be
  on `main`. Pull requests that change the packaging run the same build as a dry run.
- **Documentation-only pull requests skip lint, audit and test** (the secret scan always runs). A new
  `changes` job decides; anything outside `docs/`, `*.md` and `LICENSE` counts as code.

## [1.0.0] - 2026-11-05

First public version. Functionally identical to internal build 4.26.0.

- Version line restarted at 1.0.0 (see above).
- `docs/private/` is ignored by git.

# Pre-1.0 history (internal builds, old 4.x numbering)

Versions before 4.5.0 were not tagged in git. They are reconstructed from the
build history (see `docs/history/`). Earlier exe names are given so old copies
can be identified.

## [4.26.0] - 2026-11-04

- **AAC files (`.m4a`, `.mp4`) and damaged MP3s can be analysed.** The decoder used so far
  (libsndfile) cannot open AAC and stops at a bad MP3 frame. FFmpeg, through the new `av` package
  (PyAV), is now the second decoder: it is tried when libsndfile fails or stops early, and the longer
  result is used. FFmpeg skips damaged frames and reads on, so Adam Freeland - L.I.F.E. is decoded in
  full (379.8 s) instead of losing its last second. Of the 15 library tracks that could not be
  analysed in 4.25.1 (3 AAC, 12 damaged), all 15 decode now (the worst loses 2 s of 671 s).
  - A short complete AAC sample (a few seconds) is fine; the "at least half and 10 s" rule applies only
    to files that are damaged.
  - Tracks that failed before are tried again once at the next start (the failure version is 3 now).
  - The exe gets bigger: the PyAV wheel carries FFmpeg (about 70 MB of DLLs). That FFmpeg build is
    GPL (it includes libx264/libx265): fine for a personal tool, to be reconsidered if the exe is
    ever distributed. The packaged self-check writes and reads an AAC file.
- **The temporary library CSV (`music_test.csv`) is gone.** The app only read it on a very first
  start and when *Refresh* was pressed. A fresh install now starts with an empty library; tracks come
  in by import. **Refresh now rebuilds the list from every track in `library.sqlite`** (the collection
  of all tracks the app has ever loaded) instead of "CSV + imported tracks": without this, Refresh
  would have dropped the 2,396 tracks that only the CSV had brought in. *Load CSV* (a CSV file you
  pick) is unchanged. The packaged self-check and a test now expect an empty first start.

## [4.25.1] - 2026-11-03

- **Fixed: some tracks were never analysed ("has not been analysed yet" on the map, e.g. Adam Freeland -
  L.I.F.E.).** The MP3 had a damaged frame near its end; the decoder stopped with an error and the
  whole track was written off. A track is now analysed from what could be decoded when that is at
  least half of it (and 10 s): the vector is an average over the whole track, so a missing last few
  seconds change it very little. Of the 48 tracks in the library that had failed, 33 can be analysed
  now (they lose 7 s at the end on average, at most 114 s). The other 15 stay failed: 3 are `.m4a` /
  `.mp4` files, which the decoder cannot open at all, and 12 are broken early in the file.
  - Tracks that failed earlier are tried again once, automatically, when the app starts (the
    embeddings database is marked with a version; a future decoder improvement bumps it again).
  - Dropping a track on the map that could not be analysed now says so ("cannot be on the map: its
    audio could not be analysed (reason)") instead of "not analysed yet", which suggested waiting.

## [4.25.0] - 2026-11-03

- **Rekordbox's playlists in the Browser**, under *Rekordbox Playlists*, read straight from Rekordbox's
  own library (`master.db`), so nothing has to be exported and Rekordbox is not touched (it may be
  running or closed). They behave like Traktor's: click or drag one to show its tracks in Rekordbox's
  order (#), double-click to load it into the Playlist tab, right-click for *Import its missing tracks*
  and *Copy to my playlists...*. Folders and order are kept; Rekordbox's smartlists are listed but not
  evaluated; streaming tracks (Beatport, Apple Music) are skipped, they are not files.
  - The library is found by itself (Rekordbox's settings, else `%APPDATA%\Pioneer\rekordbox\master.db`);
    *Import > Link Rekordbox library...* picks another one. It is read from a temporary copy, in the
    background, and again whenever Rekordbox saves. If it cannot be read (e.g. a future Rekordbox
    changes its format), the Browser keeps the last playlists and the status bar says why.
  - Needs the new package `sqlcipher3-wheels` (in `requirements.txt`; the exe carries it). The
    database key is Rekordbox's well-known one, taken from the MIT-licensed pyrekordbox project.
  - Internally the Traktor playlist code is now shared with Rekordbox (`import_foreign_missing`,
    `copy_foreign_playlist`); the packaged self-check also reads a small encrypted library.

## [4.24.0] - 2026-11-03

- **The window title is now "SongSelector 4.24.0"** (name and version) instead of "Traktor Key Calculator".

- **Map and group only the listed tracks.** The new **Only listed tracks** button on the map
  arranges and groups just the tracks the List shows now (a genre, a playlist, a search result),
  so the layout, the groups and the closest-match similarities fit that set and separate it
  better than the whole library does. It takes seconds (about 0.3 s for 200 tracks, 3 s for 500).
  - It is a snapshot: change the List and press **Re-arrange map** to map the new list. Switch the
    button off to get the library map back; the library's stored layout is never touched.
  - The group summary says "of the N mapped tracks", and the List's Group column holds the groups
    of this smaller set (tracks outside it have none).

## [4.23.0] - 2026-10-30

- **Fixed: tracks dropped while the List shows a playlist were not added to it.** Dropping files
  (e.g. 136 tracks of a Traktor playlist) onto the List while it showed one of your playlists only
  imported them into the library, and the List jumped to all tracks. They are now added to that
  playlist, in the dropped order, and the List keeps showing it. Dropping onto a playlist in the
  Browser added them but also jumped to all tracks; it no longer does. The status bar says how
  many files could not be read or no longer exist.
- **Traktor's playlists in the Browser**, under *Traktor Playlists*, with Traktor's folders and
  order, read from `collection.nml` (read-only; updated when Traktor saves). Click one, or drag it
  onto the List, to show its tracks in Traktor's order (#); double-click or drag it onto the
  Playlist tab to load it. Right-click: *Import its missing tracks into the library*, *Copy to my
  playlists...* (an editable copy). Traktor's smartlists are listed with their query in the
  tooltip, but not evaluated yet.

## [4.22.0] - 2026-10-30

- **Map groups in the List.** A new **Group** column holds each track's group on the similarity
  map (1 = largest; the map's *Groups* method). Sort by it to keep similar-sounding tracks
  together; tracks not analysed or in no group sort last. A **Group colours** switch above the
  List colours its rows like the map's dots instead of by Traktor colour (the Playlist keeps its
  colours). With the map's grouping off, the switch turns on *Neighbour communities*.
  - The groups are computed in the background at start (about 9 s for 3,534 analysed tracks,
    including loading the map data) when the switch is on, or the Group column is shown and a
    grouping method is chosen; the map need not be opened.
  - Group numbers follow group size and change when the method, its setting or the analysed
    tracks change, so they are not stored and are not offered in search or Complex Search.

## [4.21.1] - 2026-10-30

- **No unshaded gap between # and Artist.** Qt kept a tree-branch indent in front of the Artist
  column (the first one internally); with # shown first, it sat between the two without the row
  colour. The List and Playlist are flat lists, so the indent is gone.

## [4.21.0] - 2026-10-30

- **Browser tab with saved playlists and smartlists.** The left pane now has two tabs:
  - **Playlist**: the set in order, with a new **#** column. Rows can be dragged to a new
    position; rows dragged in from the List are inserted where they are dropped (they used to be
    re-read from the file and appended). *Save as Playlist...* stores it under *Playlists*.
  - **Browser**, as in Traktor: *Track Collection* (All Tracks, Artists, Albums, Genres) and
    *Playlists*. Clicking an entry, or dragging it onto the List, shows only its tracks there; a
    playlist is sorted by its **#**. A bar above the List says what it shows, with *Show all
    tracks*. Search, colours and Advanced Search still filter on top.
  - **Playlists** keep tracks in order; **smartlists** keep Complex Search rows and always list
    the tracks that match them (also *None* rows, kept but ignored). Double-click or drag one onto
    the Playlist tab to load it (replace, or add after). Drag tracks onto a playlist to add them.
    Right-click: new playlist / smartlist, edit rules, rename, duplicate, delete.
  - The Complex Search dialog has *Save as Smartlist...*.
- With *Hide playlist tracks in the library* on, a saved playlist shown in the List still shows
  all its tracks (those on the Playlist tab dimmed).
- `library.sqlite` schema 3: tables `saved_lists` and `saved_list_tracks` are added on start.

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

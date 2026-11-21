# Backlog

Known issues, technical debt and ideas, roughly by priority. Move items into the
CHANGELOG when they ship.

## Next session (updated 2026-11-21, after 1.4.0)

1. [x] **Mixxx support**: shipped in 1.4.0 (PR #42), tested by the user in WSL.
2. **Model files**
   - [x] On Hugging Face, downloaded by *Get models* (1.3.0).
   - [x] *Get models* shows each model's state (a check mark for installed), and the model files are checked at
     start (size, SHA-256 once per file) (1.4.0, PR #55). The intro cut-off of 2026-11-20 did not reproduce; a test
     guards that the whole intro fits.
   - **Delete a model.** A *Delete* button per installed model (with a confirmation naming the size freed): removes
     its files, switches the model off and updates the menus. First stop anything using it: the analysis worker and
     the text-search worker may hold the ONNX file open (on Windows an open file cannot be deleted). Keep its
     embeddings cache (`embeddings-*.sqlite`) by default, so a re-download does not re-analyse; offer to delete it
     too in the same dialog.
   - [x] Cleanup (2026-11-21, user's OK): the local branch `fix/model-download-release` (replaced by the Hugging Face
     download) and the leftover draft GitHub release `models-v1` (one tokenizer asset, never public) are deleted.
   - Later: a manual GitHub Actions workflow that re-exports and uploads (pinned CPU PyTorch, verify, checksums);
     `scripts/publish_models.py` is the upload half of it.
3. [x] **Linux release** (1.3.0, PR #52). Follow-ups:
   - The user's test on a real Linux desktop: a VM with Ubuntu 24.04 (GNOME on Wayland, newer than the build's
     22.04) and Mixxx from Flathub, and a friend's machine. Check: start from the file manager, icon in the dock,
     double-click opens the player (`xdg-open`), drag into Mixxx, *Get models*, analysis, settings after a restart.
   - pip-audit runs on Windows only, so `onnxruntime` (the Linux line of `requirements.txt`) is not audited; an
     audit leg on Linux (keep the required check name, like the `test` gate).
   - `discover_collection()` still looks for `E:\DJ\TRAKTOR\collection.nml` first (see Distribution item 3);
     `SONGSELECTOR_TRAKTOR_COLLECTION` overrides it (the tests set it to `none`).
4. **Idea, to discuss later (user, 2026-11-20; "not now"):** single-key shortcuts while the app is active, e.g.
   *F* fits the map. Needs a plan for keys typed into text fields (search, description, tempo box).

## Release 1.2.0 (planned 2026-11-17)

The unreleased 1.1.4 (Top N re-cut, Match column; merged in PR #19, never tagged) and the user's feedback list of
2026-11-17 ship together as **1.2.0**: new features, so a minor version (SemVer), and one release instead of two.
One PR per block below, in this order; each with tests (a failing test first for bugs), ruff, CHANGELOG, worklog.

- [x] **A. The map follows the List** (`fix/map-follows-list`). *Only listed tracks* stored the List as a snapshot
      (`SimilarityMapWidget.only`), so after a new description search, Top N change or CLAP model switch the map
      showed only tracks that were in both the old and the new List. Now, while it is on, the map re-maps whenever
      the List changes (debounced). Button renamed **Map the List only**. Edges tooltip: "to the N most similar" is
      relative, per track, among the visible tracks (the user's question).
- [x] **B. Map interaction.** Ctrl+click on empty space (or the compared dot) ends the comparison; Esc in two steps
      (compared track first, then the selection); hover / compare cards and the label never overlap (try four
      corners, unit-tested on rectangles); *Closest matches* becomes a choice: *All*, *Harmonic*, *Edge selection*
      (only the relations checked under Edges); the old "harmonic only" setting carries over.
- [x] **F. Tag edits without freezing.** Profile first (suspect: `_save_library` rewrites every track for one
      edit). Save only the changed row; file write + re-read on a worker thread; row shows "Saving..." and reverts
      with an error if it fails; edits of one file run in order. Reusable "small background update" helper.
      *Edit track info*: the path is selectable.
- [x] **F2 (follow-up, done in 1.2.0).** Imports, *Remove from library* and *Delete duplicates* still save
      the whole library on the UI thread (2.5-5 s on the library's SSD under load, measured 2026-11-17). Move them to
      `BackgroundWriter`: append / delete only the changed rows, coalesce a burst of saves into one.
- [x] **E. Busy indicator.** One `BusySpinner` widget (runs only while busy) next to: analysis progress, map
      arranging / grouping, description search, model download, tag saving.
- [x] **C. Playlist selection on the map.** Selected Playlist tracks are shown on the map even if the List filters
      them out, in a distinct style; several at once; tracks not on a *Map the List only* map are placed near
      their most similar tracks (`place_new`). Field lookup by a dict instead of scanning the trees.
- [x] **G. Delete duplicates, three ways:** same path (today), same Artist - Title (case and spaces ignored), same
      file (same size, then same content hash; e.g. a copy in another folder). Which row stays: 1) the file still
      exists, 2) the richest row (count of filled fields: comment, colour, rating, key, BPM, genre, Song Selector
      rating / colour...), 3) on a tie the one in the Traktor / Rekordbox collection, 4) else the first. Preview
      dialog before removing; only list rows are removed, never files.
- [x] **D. Map in its own window.** Detach / Attach; closing the window docks it again; geometry saved.
- [x] **H. Cover art.** H1 (List / Playlist column, cache) and H2 (map cards, details, closest matches). Embedded pictures (ID3 APIC, FLAC, MP4), else `cover.jpg` / `folder.jpg` (also .png) next
      to the file. Thumbnails cached on disk, loaded in the background for visible rows. *Cover* column, size
      setting, two styles: cropped to the normal row height (top of the image) or square rows (rows without a
      cover keep the same height). Also in the map cards and the closest matches. No new dependency (Qt scales).
- [x] **Release:** version 1.2.0 (CHANGELOG `[1.1.4]` becomes `[1.2.0]`), fresh `.\scripts\build.ps1`, selfcheck,
      then on the real library:
  - [x] Description search: changing *Top* updates the List without a new search; *All* lists every analysed
        track; *Match* shows whole percentages, sorts correctly, is hidden in the Playlist.
  - [x] Still OK from 1.1.3: switching to LAION CLAP / Microsoft CLAP analyses its missing tracks; the window
        does not stretch; "no search: show all tracks" in the dropdown.
  - [x] Each block A-H above, as described.
  - [x] Tag `v1.2.0`; the workflow publishes the exe.

## Diagnostics (to do; asked 2026-11-17, after 1.2.0)

- [ ] **Local error log**, for when other people use the app. Today nothing is recorded: the exe has no console
      (`console=False`), so an exception in a Qt slot or override makes PyQt5 abort the app without a message, and
      errors in worker threads go to a stderr nobody sees. Industry-standard minimum, no telemetry, nothing sent:
      - `logging` to `<app data>/logs/songselector.log`, `RotatingFileHandler` (e.g. 1 MB x 3 files), level
        WARNING by default; each run starts with app version, Windows version, GPU / ONNX provider.
      - Catch what is uncaught: `sys.excepthook` (log + "something went wrong, details in the log" dialog instead
        of the silent abort), `threading.excepthook`, `qInstallMessageHandler` (Qt warnings), `faulthandler` into
        the log for native crashes (onnxruntime, DirectML).
      - The analysis and text search processes log to the same folder (own file each).
      - *Help -> Open log folder* (and maybe *Copy diagnostics*), so a user can attach the file to a bug report.
      - Not wanted: recording user interaction / usage monitoring.

## Product

- [ ] Show file details outside the main window (noted as "next step" in the v4 source `info.txt`).
- [x] Status messages use inconsistent colors: one theme-aware set since 4.10.0.
- [ ] Make the Traktor collection path a visible setting. The default
      `E:\DJ\TRAKTOR\collection.nml` is hard-coded in `core/traktor_collection.py`.
- [ ] Follow Traktor's live master BPM (idea only; nothing exists yet).
- [ ] "Key at Master BPM" column inside Traktor itself: investigated 2026-10-14, not feasible
      directly (the desktop browser is a native control). See `docs/history/`.
- [x] The bundled `music_test.csv` is gone; the library lives in `library.sqlite` and starts empty (4.26.0).
- [ ] "Remove from list" for selected rows in both panels (the collection keeps them; only the list changes).
- [x] More than one playlist: Browser tab with saved playlists and smartlists (4.21.0).
- [x] Traktor's playlists in the Browser (*Traktor Playlists*, read-only, 4.23.0).
- [x] (1.2.0) Traktor's smartlists: evaluate their queries (`$BPM > 126 & $GENRE % "break" | ...`; operators
      `== <> < <= > >= % !% ~`, `&` and `|`). Fields the app lacks: `$PLAYCOUNT`, `$TIME`
      (track length); they would have to be read from the NML. 43 in the user's collection.
- [x] Rekordbox's playlists in the Browser (*Rekordbox Playlists*, read directly from `master.db`, read-only, 4.25.0).
- [x] Mixxx's library (2026-11-20): BPM, key, rating, exact colour, playlists / crates / history, read directly from
      `mixxxdb.sqlite`; synced like Traktor. Several programs: the *primary DJ program* decides a track, the others
      fill gaps (`core/dj_programs.py`).
- [ ] Other apps' playlists (Serato, VirtualDJ, Engine DJ); Rekordbox's own ratings / colours / BPM / key as import
      sources (it has 8 track colours and stars in `master.db`): add it to `core/dj_programs.py` so the primary-program
      rule covers it.
- [ ] **TODO (decided 2026-11-20): SongSelector as an extension of the DJ programs.** Remove the app's own rating and
      colour (`Rating - Song Selector`, `Color - Song Selector`, `sscolor:`, the context-menu setters): the values
      come from Traktor / Mixxx / Rekordbox, and the app is an aid next to them, not another place to curate. Plan
      what happens to existing values first (show read-only for a while, or offer an export), then remove.
- [ ] *Optional, later:* the app's own BPM / key analysis for files no DJ program has analysed. Study how Mixxx
      does it (its analyzers use the Queen Mary Vamp plugins, e.g. `qm-tempotracker` for beats, plus a key
      detector; GPL like this project) before choosing a library.
- [ ] Folders under Playlists to organise saved playlists (later; not needed yet, 2026-10-30).
- [ ] Next-track prediction from the playlist order (the Playlist tab records the set in order;
      models and ideas in the DJ mix segmentation project). Plan only.
- [x] **Free-text search** (idea 2026-11-13, done in 1.1.0): type a description ("dark rolling DnB, reese bass") and get the
      closest tracks (top 10) in their own window; prompts can be saved and re-run. Needs a text-audio model
      (CLAP): one audio vector per track, computed in the background like CNN14, and one text vector per query,
      ranked by cosine similarity. Candidates: the light versions of LAION CLAP (`laion/clap-htsat-unfused`) and
      Microsoft CLAP (2023). **Step 1, measure first:** CPU-only cost (no CUDA assumed): library analysis time,
      query latency, memory. See `docs/research/text_search_clap.md`. Then: does it find the right tracks on
      this library; ONNX export; the window.
- [ ] **On hold:** suggest missing Traktor ratings / colours from the sound. Research only, no app feature
      (start: `docs/research/rating_color_prediction.md`, `rating_color_plan.md`). So far CNN14, MusiCNN,
      Discogs-EffNet and OpenL3 are equally (un)able to predict them: probably the labels, not the model.
      To continue: fill `docs/research/sheets/rerate_2026-11-03.csv` (blind re-rating, 60 tracks) and
      `valid_cnn14_2026-11-03.csv` (yes/no), then run `taste_sheets.py rerate-score` / `valid-score`
      (see `docs/research/sheets/README.md`). Larger models (MAEST, MERT, CLAP) not tried yet.
- [x] Audio embeddings (PANNs CNN14, 5 s chunks) for every library track, analysed in the background (4.7.0).
- [x] **Similarity view**: first version in 4.11.0 (2D map, closest matches, harmonic edges). Follow-ups below.
- [x] Map: "edges only to the N closest matches" (harmonic *and* similar): 4.16.0, with opacity by similarity.
- [x] Map: 3D view, 4.19.0: 3D t-SNE projected onto the same scene (no OpenGL dependency),
      Shift+drag rotates, depth fades far dots. Follow-up: a 3D-aware "Map density" grouping
      (it still uses the 2D positions); compare whether 3D splits the "one big blob" better.
- [x] Background sync from Traktor's collection.nml (key, BPM, colour, rating), 4.19.0.
      Follow-up: write the Song Selector rating/colour back to Traktor (needs care: Traktor
      overwrites the NML when it closes).
- [x] Map: **unsupervised clustering**, shipped in 4.16.0 (k-means, neighbour communities, map
      density). Follow-ups: name groups by their most common genre; filter the list by group.
      Original plan, method chosen in the map settings, to try several
      (user request 2026-10-28: the map is mostly one big blob, yet some groups are expected).
      Colour dots by cluster as an alternative to the Traktor colour; cluster sizes in the status.
      Lightweight candidates (numpy only, the exe has no scikit-learn; seconds on 5k tracks):
      1. k-means (cosine) on the full vectors reduced by PCA to ~50 dims; k from the user or by
         silhouette score.
      2. Graph communities on the k-nearest-neighbour graph (label propagation or Louvain): finds
         groups even inside a blob, because it follows neighbours instead of gaps in density.
      3. Density clustering (HDBSCAN-style) on the 2D map positions: groups exactly what the eye
         sees; tracks in sparse areas stay unclustered.
      Possibly first: check whether the blob comes from the vectors themselves (PCA whitening,
      dropping the first few dominant components) rather than from t-SNE; measure with the
      genre/colour labels as in `docs/research/audio_embeddings.md`.
- [ ] Map: faster layout for very large libraries (Barnes-Hut t-SNE, or arrange a sample + place_new).
- [ ] Map: lasso selection, labels for the selected track's neighbours, a legend for the edge colours.
- [ ] Re-check the per-track vector (`similarity.track_vectors`) once more styles are analysed.
- [x] **Several embedding models, chosen by the user** (asked 2026-11-13, done in 1.1.0). Today: CNN14 only. Add the CLAP models
      that work in research (LAION `clap-htsat-unfused`, Microsoft CLAP 2023; `laion/larger_clap_music` collapsed in
      transformers 4.57, see `docs/research/text_search_clap.md`). The user picks which models are kept up to date
      (each is analysed in the background and follows new and changed files, as CNN14 does now) and which one the
      similarity map, closest matches and groups use. Steps, one PR each:
      1. ONNX exports of both CLAP encoders with verification against PyTorch, like `scripts/export_cnn14_onnx.py`;
         LAION's mel features reimplemented in numpy (no transformers/torch in the exe); tokenizers for the text side.
         Measure ONNX Runtime on CPU and DirectML. This is the risky step: prove it before the app work.
      2. Embedding store and analysis per model (the store already has a `model` column); settings for "models to
         analyse" and "model for the map"; map layouts per model; decode each file once for all models.
      3. Free-text search window (top tracks for a typed description, saved prompts).
- [ ] Research: which model for the similarity map (observed 2026-11-20 on a DnB + house/downtempo playlist): CNN14
      separates the genres clearly, LAION CLAP mixes them more. Expected: CNN14 is an AudioSet classifier whose labels
      include music genres (and it sees rhythm/tempo in 5 s windows); LAION's general model learned from captions of
      mostly non-music sounds, so it groups by described qualities (dark, calm, vocal) across genres. Keep CNN14 for
      the map for now; measure instead of eyeballing t-SNE (neighbour purity with the user's labels, as in
      `rating_color`); try LAION's music-trained `larger_clap_music`. Microsoft CLAP can go later.
- [ ] Research, low priority: a better similarity than cosine for CNN14 (classifier features, not trained for
      similarity; CLAP is trained on cosine, so it stays): PCA whitening, hubness reduction (CSLS), window-set
      comparison (Chamfer / Fréchet), or a learned metric from the user's playlists and sets. Evaluate with the user's
      labels, as above.
- [x] int8 models (2026-11-20, `docs/research/experiments/results/2026-11-20_int8_benchmark.md`): naive dynamic
      quantization was slower everywhere and broke the embeddings (the spectrogram front-end got quantized). Not
      worth it on the GPU; a fair CPU test (front-end in float, only LAION's MatMuls) is open if CPU speed matters.
      **Closed 2026-11-20 (user's decision):** no quantized models; only the float32 files are published.
- [ ] Research: do CLAP embeddings group tracks by *feel* better than CNN14 (asked 2026-11-13)? CLAP is trained to
      match descriptions ("dark", "uplifting", "groovy"), CNN14 to label sound events, so its neighbourhoods may follow
      mood and energy more. Compare on the same tracks: style purity of the 10 nearest (as for CNN14), plus a blind
      listening check ("do these 10 feel alike?") with the DJ.
- [x] Track similarity from the embeddings (`core/similarity.py`, 4.11.0).
- [x] GPU in the exe: DirectML since 4.9.0 (CUDA stays optional from source, requirements-gpu.txt).
- [x] **Download the models from inside the app** (asked 2026-11-13, done in 1.1.0; the GitHub release planned
      below was never published. Since 2026-11-20 the files are on Hugging Face, one repo per model, uploaded with
      `scripts/publish_models.py`; the manual CI workflow below is still open). Today every model has to be
      built with an export script that needs PyTorch, so for anyone but the developer the app has no embeddings
      (CNN14's default path only exists on the development machine; the CLAP entries show "model files missing").
      Design:
      - **Hosting:** the exported files (7 files, 1.6 GB in all, the largest 505 MB) as assets of a separate GitHub
        release, e.g. tag `models-v1` (not tied to app versions), with `SHA256SUMS.txt` and the three licences
        (CNN14 CC BY 4.0: attribution; LAION Apache 2.0; Microsoft CLAP MS-PL: licence text must go along).
        Uploaded once from a local export (`gh release upload`); GitHub allows up to 2 GB per asset.
      - **App:** *Analysis -> Download models...*: one row per model with size, licence and status; downloads in a
        thread into the models folder next to the app (`.part` files, resumable, SHA-256 checked before the file
        gets its real name), then the model can be switched on. The first start without any model offers it.
      - **CI:** not in the normal pipeline (1.6 GB per run). A manual workflow (`workflow_dispatch`) downloads the
        assets, checks the hashes and runs `verify_release -Model ... -ClapModels ...` on the exe, run before a
        release that changes models. Unit tests use a small local HTTP server and a fake file.
- [ ] Row shading by *Color - Song Selector* as a third coloring mode.
- [x] Rating / color for several selected rows at once (4.8.0).
- [ ] Undo for "Remove from library" (today: Refresh rebuilds the full list).
- [ ] Edit track info for several rows at once (e.g. set the genre of 20 tracks).

## Performance (measured on 5,105 tracks, 2026-10-27)

- [x] Startup feedback: splash screen from the first moment (2026-11-13). Measured then on 3,753 tracks: the window
      takes ~3 s from Python's start (imports 0.7 s, window 2.3 s: tables ~1.2 s, `collection.nml` ~1.1 s), and the
      one-file exe adds ~4-5 s of unpacking before that (7.6 s to the window in total). Embeddings are *not* read at
      startup: analysis compares file fingerprints only, the map loads vectors when it is opened.
- [ ] Faster start: a one-folder build removes the unpacking (see Distribution, item 5); parse `collection.nml`
      after the window is shown.

- [ ] Startup ~1.7 s: building the tree rows ~1.2 s (`populate_tree` / `_track_item`) and parsing
      `collection.nml` ~1.1 s (`TraktorCollection._load`); the two overlap in the profile. Loading the
      list from SQLite is only ~0.05 s. Options: QTreeView with a model instead of QTreeWidget items;
      cache the NML index keyed by the file's mtime.
- [ ] `_rows_by_path` uses `DataFrame.iterrows` (~0.5 s on 5k rows); use vectorised lookups.
- [x] (1.2.0, F2) Saving the library list after each import rewrites all 5k tracks (~0.2 s); upsert only the
      changed tracks and rewrite only the list order.

## Distribution to other users

The exe is already self-contained (Python, Qt, pandas, ...), but it is set up for one machine.
Do 1–2 first; they matter even without an installer.

- [x] 1. Ship without the developer's library: done in 4.26.0, the bundled CSV is removed and a
      fresh install starts with an empty library.
- [ ] 2. Store user data in `%LOCALAPPDATA%\SongSelector\` instead of next to the exe.
      `C:\Program Files` is not writable for normal users, so today the app would fail with
      "Cannot start" there. Keep a "portable" mode (data next to the exe) when a marker file exists,
      and migrate existing data from the exe folder on first start.
- [ ] 3. Remove machine-specific defaults: the default embedding model
      `E:\GITHUB_E\MusicFindBoundaries\cnn14.onnx` (`config.DEFAULT_EMBEDDING_MODEL`), the `E:\DJ\TRAKTOR\collection.nml` default
      (keep the Documents\Native Instruments auto-detection) and the real-file test samples.
- [ ] 4. Test on a clean Windows 10/11 VM (no Python, no Traktor).
- [ ] 5. Installer: PyInstaller one-folder build (faster start, fewer antivirus false positives
      than one-file) + Inno Setup script `packaging/installer.iss`, giving
      `SongSelector-Setup-<version>.exe` with Start menu entry and uninstaller.
      MSI (WiX) or MSIX only if needed for corporate or Store distribution.
- [ ] 6. Code signing, to avoid the SmartScreen "Windows protected your PC" warning.
- [ ] 7. Large optional components (the models, 1.6 GB) as a separate download on demand, never inside the
      installer: see "Download the models from inside the app" above.
- [ ] 8. Update check (later): compare with the latest GitHub release tag.

## Code health

Assessment 2026-10-27: new modules are small and documented, but `ui/main_window.py` (1,577 lines,
one class) and `core/key_tables.py` (850 lines, mostly thesis leftovers) are not yet
human-friendly. Suggested next step, before more features: a behaviour-preserving cleanup pass.

- [x] **Rename everything to SongSelector** (asked 2026-11-05, done 2026-11-13): package `songselector`,
      exe `SongSelector-<version>.exe`, `MainWindow`, `SONGSELECTOR_*` environment variables (the old `TRAKTOR_*`
      names are read as a fallback until 1.2), settings file `SongSelector_settings.json` (migrated once from
      `SpotNextTrack_settings.json`). Names that mean Native Instruments' Traktor stay.
      - [ ] In the release after 1.1: remove the `TRAKTOR_*` fallback in `env.py` and the `~/.traktor_key_calculator`
        fallback in `config.py`. Keep the settings-file migration longer (it is cheap and protects old installs).

- [ ] `config.py` mixes constants, the `AudioMetadata` dataclass and Qt colors; split it so
      `core/` does not depend on PyQt5.
- [ ] `ui/main_window.py` (~1000 lines) holds most of the state; extract library/table logic
      into `core/`, where it can be unit-tested without Qt.
- [ ] `core/key_tables.py` contains unused leftovers from the thesis project
      (`model_feature_cols`, `jamendo_instrument`, ...). Remove them and keep only the tables in use.
- [ ] `core/key_calculator.py` and `core/key_formats.py` both model notes; consolidate on one.
- [x] Remove dead code (`test = 100` in `config.py`; duplicate imports went with ruff in 1.0.1).
- [x] Linter: ruff, pinned, required in CI since 1.0.1. A formatter (`ruff format`) is still open.
- [x] Tests that rely on real files under `E:\DJ\...` are marked `local_data` and deselected in CI; the same
      logic is covered by generated fixtures (1.0.1).
- [ ] Consider dropping pandas (large dependency, used only for a simple table).
- [x] CI: pytest on GitHub Actions (windows-latest, Python 3.11), plus lint, pip-audit and gitleaks (1.0.0–1.0.1).

# Backlog

Known issues, technical debt and ideas, roughly by priority. Move items into the
CHANGELOG when they ship.

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
- [ ] Traktor's smartlists: evaluate their queries (`$BPM > 126 & $GENRE % "break" | ...`; operators
      `== <> < <= > >= % !% ~`, `&` and `|`). Fields the app lacks: `$PLAYCOUNT`, `$TIME`
      (track length); they would have to be read from the NML. 43 in the user's collection.
- [x] Rekordbox's playlists in the Browser (*Rekordbox Playlists*, read directly from `master.db`, read-only, 4.25.0).
- [ ] Other apps' playlists (Serato, VirtualDJ, Engine DJ); Rekordbox's own ratings / colours / BPM / key as import sources.
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
- [ ] Research: do CLAP embeddings group tracks by *feel* better than CNN14 (asked 2026-11-13)? CLAP is trained to
      match descriptions ("dark", "uplifting", "groovy"), CNN14 to label sound events, so its neighbourhoods may follow
      mood and energy more. Compare on the same tracks: style purity of the 10 nearest (as for CNN14), plus a blind
      listening check ("do these 10 feel alike?") with the DJ.
- [x] Track similarity from the embeddings (`core/similarity.py`, 4.11.0).
- [x] GPU in the exe: DirectML since 4.9.0 (CUDA stays optional from source, requirements-gpu.txt).
- [ ] **Download the models from inside the app** (asked 2026-11-13; next after 1.1.0). Today every model has to be
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
- [ ] Saving the library list after each import rewrites all 5k tracks (~0.2 s); upsert only the
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

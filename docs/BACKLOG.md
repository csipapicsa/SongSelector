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
- [x] Track similarity from the embeddings (`core/similarity.py`, 4.11.0).
- [x] GPU in the exe: DirectML since 4.9.0 (CUDA stays optional from source, requirements-gpu.txt).
- [ ] Download the embedding model on demand (first use) instead of choosing the file by hand.
- [ ] Row shading by *Color - Song Selector* as a third coloring mode.
- [x] Rating / color for several selected rows at once (4.8.0).
- [ ] Undo for "Remove from library" (today: Refresh rebuilds the full list).
- [ ] Edit track info for several rows at once (e.g. set the genre of 20 tracks).

## Performance (measured on 5,105 tracks, 2026-10-27)

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
- [ ] 2. Store user data in `%LOCALAPPDATA%\TraktorKeyCalculator\` instead of next to the exe.
      `C:\Program Files` is not writable for normal users, so today the app would fail with
      "Cannot start" there. Keep a "portable" mode (data next to the exe) when a marker file exists,
      and migrate existing data from the exe folder on first start.
- [ ] 3. Remove machine-specific defaults: the default embedding model
      `E:\GITHUB_E\MusicFindBoundaries\cnn14.onnx` (`config.DEFAULT_EMBEDDING_MODEL`), the `E:\DJ\TRAKTOR\collection.nml` default
      (keep the Documents\Native Instruments auto-detection) and the real-file test samples.
- [ ] 4. Test on a clean Windows 10/11 VM (no Python, no Traktor).
- [ ] 5. Installer: PyInstaller one-folder build (faster start, fewer antivirus false positives
      than one-file) + Inno Setup script `packaging/installer.iss`, giving
      `TraktorKeyCalculator-Setup-<version>.exe` with Start menu entry and uninstaller.
      MSI (WiX) or MSIX only if needed for corporate or Store distribution.
- [ ] 6. Code signing, to avoid the SmartScreen "Windows protected your PC" warning.
- [ ] 7. Large optional components (the 327 MB embedding model) as a separate download on demand,
      never inside the installer.
- [ ] 8. Update check (later): compare with the latest GitHub release tag.

## Code health

Assessment 2026-10-27: new modules are small and documented, but `ui/main_window.py` (1,577 lines,
one class) and `core/key_tables.py` (850 lines, mostly thesis leftovers) are not yet
human-friendly. Suggested next step, before more features: a behaviour-preserving cleanup pass.


- [ ] `config.py` mixes constants, the `AudioMetadata` dataclass and Qt colors; split it so
      `core/` does not depend on PyQt5.
- [ ] `ui/main_window.py` (~1000 lines) holds most of the state; extract library/table logic
      into `core/`, where it can be unit-tested without Qt.
- [ ] `core/key_tables.py` contains unused leftovers from the thesis project
      (`model_feature_cols`, `jamendo_instrument`, ...). Remove them and keep only the tables in use.
- [ ] `core/key_calculator.py` and `core/key_formats.py` both model notes; consolidate on one.
- [ ] Remove dead code (`test = 100` in `config.py`, duplicate imports in `ui/main_window.py`).
- [ ] Add a formatter/linter (e.g. ruff) once the code above is cleaned up.
- [ ] Tests that rely on real files under `E:\DJ\...` should use bundled fixtures instead.
- [ ] Consider dropping pandas (large dependency, used only for a simple table).
- [ ] CI: run `pytest` on GitHub Actions (windows-latest, Python 3.11).

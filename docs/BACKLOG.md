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
- [ ] Replace the bundled `music_test.csv` with a library built from the user's own collection.
- [ ] "Remove from list" for selected rows in both panels (the collection keeps them; only the list changes).
- [ ] More than one playlist: the store already supports named lists (`library_store.py`); needs UI.
- [x] Audio embeddings (PANNs CNN14, 5 s chunks) for every library track, analysed in the background (4.7.0).
- [x] **Similarity view**: first version in 4.11.0 (2D map, closest matches, harmonic edges). Follow-ups below.
- [ ] Map: "edges only to the N closest matches" (harmonic *and* similar), likely the most useful edge mode.
- [ ] Map: 3D view (pyqtgraph.opengl or vispy).
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

- [ ] 1. Ship without the developer's library: `data/music_test.csv` holds the developer's own
      2,920 tracks with `E:\DJ\...` paths. New users should start with an empty library
      (keep the CSV as a test fixture only).
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

# Backlog

Known issues, technical debt and ideas, roughly by priority. Move items into the
CHANGELOG when they ship.

## Product

- [ ] Show file details outside the main window (noted as "next step" in the v4 source `info.txt`).
- [ ] Status messages use inconsistent colors (v4 `info.txt`: "some messages are green red whatever").
- [ ] Make the Traktor collection path a visible setting. The default
      `E:\DJ\TRAKTOR\collection.nml` is hard-coded in `core/traktor_collection.py`.
- [ ] Follow Traktor's live master BPM (idea only; nothing exists yet).
- [ ] "Key at Master BPM" column inside Traktor itself: investigated 2026-10-14, not feasible
      directly (the desktop browser is a native control). See `docs/history/`.
- [ ] Replace the bundled `music_test.csv` with a library built from the user's own collection.
- [ ] "Remove from list" for selected rows in both panels (the collection keeps them; only the list changes).
- [ ] More than one playlist: the store already supports named lists (`library_store.py`); needs UI.
- [ ] Audio embeddings (PANNs CNN14, 5 s chunks) for every track. See `docs/research/audio_embeddings.md`.

## Performance (measured on 5,105 tracks, 2026-10-27)

- [ ] Startup ~1.7 s: building the tree rows ~1.2 s (`populate_tree` / `_track_item`) and parsing
      `collection.nml` ~1.1 s (`TraktorCollection._load`); the two overlap in the profile. Loading the
      list from SQLite is only ~0.05 s. Options: QTreeView with a model instead of QTreeWidget items;
      cache the NML index keyed by the file's mtime.
- [ ] `_rows_by_path` uses `DataFrame.iterrows` (~0.5 s on 5k rows); use vectorised lookups.
- [ ] Saving the library list after each import rewrites all 5k tracks (~0.2 s); upsert only the
      changed tracks and rewrite only the list order.

## Code health

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

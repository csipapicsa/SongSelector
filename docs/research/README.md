# Research notes

Findings that are worth keeping, with the numbers and the way they were measured, so they can be
checked or repeated later. Decisions made from them go into `docs/ARCHITECTURE.md` and
`docs/BACKLOG.md`.

| Note | What it holds |
|---|---|
| [audio_embeddings.md](audio_embeddings.md) | Why PANNs CNN14, how embeddings are computed and stored, speed measurements, similarity and map layout (2026-10) |
| [rating_color_prediction.md](rating_color_prediction.md) | Can the sound predict a track's rating or colour? Findings so far, literature (2026-11) |
| [rating_color_plan.md](rating_color_plan.md) | The research plan for that question: validation rules, steps, stop rules |
| [model_candidates.md](model_candidates.md) | Other embedding models: licence, size, input, cost to integrate |
| [landscape_dj_tools.md](landscape_dj_tools.md) | Other free / open-source / commercial DJ library and next-track tools, research papers (web search 2026-11) |
| [text_search_clap.md](text_search_clap.md) | Free-text track search with CLAP: CPU cost of LAION vs Microsoft CLAP (analysis time, query latency, memory) (2026-11) |
| [rekordbox_import.md](rekordbox_import.md) | Can Rekordbox playlists be imported? What is on this machine, XML export vs reading master.db |
| [experiments/](experiments/) | Runnable code (`# %%` scripts that open as notebooks in VS Code) and one small JSON of results per run |

Conventions

- Write the date, the data (how many tracks) and the setup next to every number.
- A result that was not measured is marked *to measure*, never guessed.
- Experiments run with the system Python (numpy, scikit-learn, torch, transformers), not the
  app's `.venv`: nothing here changes the app or the exe. Downloaded models, data snapshots and
  extracted vectors go to `.research_cache/` (git-ignored).
- Experiments read a **copy** of the app's database files, never the originals.

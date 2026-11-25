# Research notes

Findings that are worth keeping, with the numbers and the way they were measured, so they can be
checked or repeated later. Decisions made from them go into `docs/ARCHITECTURE.md` and
`docs/BACKLOG.md`. The code, data and result files behind them are in [research/](../../research/README.md).

| Note | What it holds |
|---|---|
| [audio_embeddings.md](audio_embeddings.md) | Why PANNs CNN14, how embeddings are computed and stored, speed measurements, similarity and map layout (2026-10) |
| [rating_color_prediction.md](rating_color_prediction.md) | Can the sound predict a track's rating or colour? Findings so far, literature (2026-11) |
| [rating_color_plan.md](rating_color_plan.md) | The research plan for that question: validation rules, steps, stop rules |
| [model_candidates.md](model_candidates.md) | Other embedding models: licence, size, input, cost to integrate |
| [landscape_dj_tools.md](landscape_dj_tools.md) | Other free / open-source / commercial DJ library and next-track tools, research papers (web search 2026-11) |
| [text_search_clap.md](text_search_clap.md) | Free-text track search with CLAP: CPU cost of LAION vs Microsoft CLAP (analysis time, query latency, memory) (2026-11) |
| [allmusiccaps_clap.md](allmusiccaps_clap.md) | MTG's music-trained CLAP (AllMusicCaps, OMAR-RQ encoder) vs LAION CLAP: desk comparison, hands-on checks, ONNX export probe, plan to measure; notebook [research/experiments/clap/allmusiccaps.ipynb](../../research/experiments/clap/allmusiccaps.ipynb) (2026-11) |
| [research/experiments/distill/](../../research/experiments/distill/README.md) | A small student network in AllMusicCaps' audio space for CPU-only machines: Phase 0 speed (a student takes 20x less CPU time per track than the app today, but only ~1.5-2.7x less wall time than the teacher on 6 windows, because decoding dominates); Phase 1 training (a 1 MB CNN matches the teacher on genre-tag search and beats LAION; its closest matches differ from the teacher's) (2026-11) |
| [allmusiccaps_distillation_brief.md](allmusiccaps_distillation_brief.md) | The distillation brief: objective, prior work, experiment matrix, losses, evaluation protocol (written before any training, 2026-11-25) |
| [allmusiccaps_distillation_phase2.md](allmusiccaps_distillation_phase2.md) | Review of Phase 1 and the Phase 2 plan: split audit, losses (centring, relational, text-aware), experiment matrix E00-E13 (2026-11-25) |
| [rekordbox_import.md](rekordbox_import.md) | Can Rekordbox playlists be imported? What is on this machine, XML export vs reading master.db |

Conventions

- Write the date, the data (how many tracks) and the setup next to every number.
- A result that was not measured is marked *to measure*, never guessed.
- How experiments run (their own venvs, `.research_cache/`, a copy of the app's database, no track names in
  results): [research/README.md](../../research/README.md).

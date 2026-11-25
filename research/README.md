# Research code

The experiments behind the app's decisions: runnable code, the small hand-made data they use, and one result file per
run. What was found, and why it matters, is written up in [docs/research/](../docs/research/README.md); decisions go
into [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) and [docs/BACKLOG.md](../docs/BACKLOG.md).

Nothing here is part of the app: `src/` never imports it and the exe does not contain it. Code that graduates into the
app is rewritten in `src/` with tests.

| Folder | What |
|---|---|
| [experiments/clap/](experiments/clap/) | CLAP for free-text search: CPU benchmark, embedding extraction, AllMusicCaps ONNX export, notebooks |
| [experiments/distill/](experiments/distill/README.md) | A small student network in AllMusicCaps' audio space for CPU-only machines (own README) |
| [experiments/quantization/](experiments/quantization/) | int8 models: speed and quality against fp32 |
| [experiments/rating_color/](experiments/rating_color/) | Can the sound predict a DJ's ratings and colours? |
| [data/](data/) | Small inputs made by hand, committed: the [prompt set](data/allmusiccaps_prompts.md) for free-text search, the rating [sheets](data/sheets/README.md) |
| [results/](results/) | One file per run, `<date>_<what>.json`; committed with the write-up |

Not here: `.research_cache/` at the repo root (git-ignored) holds everything large or personal: downloaded models,
library snapshots, extracted vectors, feature caches, MLflow stores and the research venvs (`venv-clap`,
`venv-distill`, `venv-ort-cuda`).

## Running

- Run from the repo root with the venv the script names in its docstring (or its README). Research venvs live in
  `.research_cache/`, never the app's `.venv`, so torch and friends never reach the app or the exe. The exceptions say
  so: a script that measures the app's own runtime runs in `.venv`.
- Scripts are `# %%` files: VS Code opens them as notebooks, and they also run as plain scripts.
- Scripts find the repo from their own location (`Path(__file__).parents[3]`), notebooks by walking up to
  `pyproject.toml`, so the working folder does not matter. They import the app from `src/` to decode and window audio
  exactly as the app does.

## Rules

- Read a **copy** of the app's database files (a snapshot in `.research_cache/`), never the originals.
- Result files hold numbers, settings and dates, never track names or paths: the library is personal.
- A result file is a record of one run: not edited afterwards. A new run is a new file.
- Write the date, the data (how many tracks) and the setup next to every number. A result that was not measured is
  marked *to measure*, never guessed.
- CI lints this folder with ruff, like `src/` and `tests/`. The app's tests do not run for a research-only change.

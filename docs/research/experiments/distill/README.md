# AllMusicCaps distillation: a small audio encoder for CPU-only machines

**Question:** can a small network, fed cheap log-mel features, put tracks into the AllMusicCaps CLAP audio space
well enough for the map, closest matches and free-text search, at a fraction of the CPU cost? The original text
encoder stays, so typed queries keep working. Background and literature: the distillation brief
(`docs/research/AllMusicCaps_distillation_project - 2026-11-125.md`) and [../../allmusiccaps_clap.md](../../allmusiccaps_clap.md).

**Why:** on a GPU the teacher is already fast (~24 ms per 10 s window on DirectML). On the CPU it takes
112-217 ms per window, and the app embeds every window, so 4-8 s per 6-minute track. Users without a GPU carry
that load.

## Phases

| Phase | Question | Status |
|---|---|---|
| 0 | Is a student really cheaper end to end (decode + features + model)? Random weights: speed does not depend on training | done 2026-11-25: yes, see results |
| 1 | How close can a trained student get? Teacher targets: the 130,705 window vectors already in the app's cache (3,380 tracks), no teacher runs needed | next |
| 2 | Best student to ONNX (int8?), app integration as its own model entry | after 1 |

## Phase 0 results, 2026-11-25

**Setup:** Intel i5-10300H (4 cores, 8 threads), 34 GB RAM, Windows 11; onnxruntime-directml 1.24.4, CPU provider,
the app's session options; 10 random library tracks from the teacher cache (70 minutes, 426 windows, seed 1),
decoded with the app's decoder; batch 8; students with random weights. One run, laptop in normal use (VS Code
open), so the run-to-run variation is not measured. Raw numbers:
[../results/2026-11-25_distill_phase0_speed.json](../results/2026-11-25_distill_phase0_speed.json).

**Per 6-minute track,** end to end (decode + model). CPU-s is CPU time over all threads, i.e. the load on the
machine; a library of 5,000 tracks is the DJ's library.

| Pipeline | Threads | Wall s | CPU-s | 5,000 tracks | Model file | RAM after load |
|---|---|---|---|---|---|---|
| Teacher, every window (**the app today**) | 4 | 5.87 | 21.2 | 8.2 h | 296 MB | 379 MB |
| Teacher, every window | 1 | 12.92 | 12.8 | 17.9 h | | |
| Teacher, 6 windows | 4 | 1.60 | 4.19 | 2.2 h | | |
| Teacher, 6 windows | 1 | 2.83 | 2.79 | 3.9 h | | |
| Student `cnn4-64`, every window | 1 | 2.36 | 2.34 | 3.3 h | 2.7 MB | 64 MB |
| Student `cnn4-64`, 6 windows | 1 | **1.04** | **1.04** | 1.4 h | | |
| Decoding alone (24 kHz), mean of all runs | - | 0.81 | 0.86 | 1.1 h | | |

**Per window** (10 s, batch 1, median, 1 thread): teacher 379 ms (123 ms on 4 threads).

| Student | Params | File | ms / window | 6 windows, s / track |
|---|---|---|---|---|
| `mfcc40-mlp` (about the front end alone) | 0.30 M | 1.4 MB | 26.9 | 0.94 |
| `cnn4-small-64` | 0.23 M | 1.1 MB | 30.3 | 0.96 |
| `mnv3s-128` | 1.52 M | 6.3 MB | 33.2 | 1.03 |
| `cnn4-64` | 0.65 M | 2.7 MB | 41.4 | 1.04 |

**What it means:**

1. **Against the app today** a student with 6 windows is 5.6x faster per track and takes 20x less CPU time
   (1.04 vs 21.2 CPU-s), with a 3 MB file instead of 296 MB and ~315 MB less memory.
2. **Against the fair baseline,** the teacher with 6 windows, wall time gains only 1.5x (teacher on 4 threads) to
   2.7x (1 thread): decoding is ~80% of the student's total (Amdahl's law). CPU time is still 4x lower than the
   4-thread teacher. The case for a student is CPU load, memory and download size more than seconds per track.
3. **Student size hardly matters:** all four take 0.94-1.04 s per track with 6 windows. Most of a student's model
   time is the log-mel front end (~27 ms per window in ONNX). Phase 1 can choose the architecture on quality
   alone, and a larger student (a few million parameters) still fits the budget.
4. **Students gain nothing from threads** (27 vs 26 ms per window), so they run on 1 thread: the lightest load,
   analysis can run in the background.
5. **Front end:** numpy's FFT gives the same log-mel (max difference 2e-6) in 13.8 ms instead of 27 ms. That saves
   ~0.08 s per track at 6 windows: not worth leaving the "raw audio in, embedding out" contract for now.
6. **Peak memory is decoding,** not the model: a whole track as float32 (students peak at 465-535 MB but hold only
   ~64 MB after loading).
7. **Independent of distillation:** the 6-window sampling (decided 2026-11-22, not in the app yet) makes the
   teacher 3.7x faster on the CPU at no quality cost. The next lever after that is decoding: 6 windows need only
   60 s of a 6-minute track, so decoding only those parts would cut the 0.8 s floor for both.

**Decision:** Phase 1 is worth doing.

## Phase 1 plan

- **Data:** the frozen snapshot of the app's teacher cache (`common.teacher_cache()`), all tracks except the
  genre test set of [../clap/allmusiccaps.ipynb](../clap/allmusiccaps.ipynb), so the student can be scored with
  the same 27 prompts (teacher 0.328 mean AP, LAION 0.214). Split by artist where possible.
- **Learning curve:** 500, 1,000 and all ~2,400 training tracks, to see whether more data still helps.
- **Short runs:** AdamW, fixed learning rate 3e-4, at most 30 epochs, early stopping after 3 epochs without
  better validation cosine. Learning-rate schedules only after a baseline works.
- **Order:** mean-vector baseline, MFCC + ridge, then the CNNs. Features from 6 windows per track first (~20k
  windows), cached as float16.
- **Note:** the cached teacher vectors are not unit length (norms ~3), so the loss compares directions (cosine).

## Setup

A separate venv, so nothing here changes the app's `.venv` or the exe (torch 2.8 CUDA for training on the
4 GB GPU; onnxruntime-directml 1.24.4, the app's runtime, for fair speed numbers):

```
uv venv .research_cache\venv-distill --python 3.12
uv pip install --python .research_cache\venv-distill\Scripts\python.exe torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu126
uv pip install --python .research_cache\venv-distill\Scripts\python.exe -r docs\research\experiments\distill\requirements.txt
```

If C: is short of space, point `UV_CACHE_DIR`, `TMP` and `TEMP` at a folder on another drive first.

## Files

| File | What |
|---|---|
| [common.py](common.py) | Paths, the teacher's contract (24 kHz, 10 s windows, 512-d), the app's decoder and windowing, reading the teacher cache |
| [students.py](students.py) | Student networks with the log-mel front end inside; `python students.py` exports them (random weights) to ONNX and checks ONNX against PyTorch |
| [benchmark_speed.py](benchmark_speed.py) | Phase 0: teacher vs students on the CPU, each (model, threads) in a fresh process |
| [requirements.txt](requirements.txt) | Pinned versions of the venv |

Outputs: `.research_cache/distill/` (git-ignored: ONNX files, feature cache, MLflow store) and one small JSON
per run in [../results/](../results/).

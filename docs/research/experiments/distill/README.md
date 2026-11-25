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
| 1 | How close can a trained student get? Teacher targets: the 130,705 window vectors already in the app's cache (3,380 tracks), no teacher runs needed | done 2026-11-25: on genre search a 1 MB student matches the teacher; closest matches differ, see results |
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

- **Data** ([prepare_data.py](prepare_data.py)): the frozen snapshot of the app's teacher cache (3,380 tracks).
  Split so that no artist is shared between training and evaluation:
  - **test:** the 1,272 tracks of the genre test set of [../clap/allmusiccaps.ipynb](../clap/allmusiccaps.ipynb)
    (rating 4-5 with a colour). The student is scored there with the same 27 prompts, labels and AP as the
    teacher.
  - **val:** the 608 other tracks by the test set's artists. They would leak those artists into the test score
    if used for training, but they share no artist with training, so they serve early stopping and model choice.
  - **train:** the remaining 1,500 tracks, with up to 16 evenly spaced windows each (~24k windows; val and test use
    the 6 sampled windows). A seeded order gives nested subsets of 500 / 1,000 / 1,500 tracks for a learning curve.
- **Inputs:** 64-band log-mels computed by the students' own front end on the GPU, cached as float16 (~4.5 GB).
  The front end has no learned weights, so training from the cache equals training the exported model. Checked
  before the build: fresh teacher inference on cached windows gives cosine 1.00000 with the cached targets
  (another window of the same song: 0.25-0.92).
- **Training** ([train.py](train.py)): loss 1 - cosine (the cached teacher vectors are not unit length, norms ~3,
  and the app compares directions); AdamW, fixed learning rate 3e-4, batch 32, fp32, at most 10 epochs, early
  stopping after 3 epochs without a better validation cosine. No augmentation. Learning-rate schedules only once a
  baseline works.
- **Order:** references (teacher on 6 windows, LAION CLAP), the mean-vector baseline, MFCC + ridge, then the
  students; then the learning curve for the best one. `mnv3s-128` needs a 128-band cache; only if the 64-band
  students fall short.
- **Evaluation** ([evaluate.py](evaluate.py)): fidelity to the teacher (window cosine, track cosine, top-10
  overlap of each track's nearest tracks) and test genre AP. Everything goes to MLflow (experiment `distill-train`).

## Phase 1 results, 2026-11-25

**Setup:** as planned above, except mixed precision: fp16 gives NaN from the first step on the GTX 1650 Ti (and is
slower there), so training runs in fp32. Batch 32, AdamW 3e-4, at most 10 epochs, patience 3; 23,920 training
windows from 1,500 tracks. One run per model (seed 0). Raw numbers:
[../results/2026-11-25_distill_phase1.json](../results/2026-11-25_distill_phase1.json); charts:
[phase1_eval.ipynb](phase1_eval.ipynb).

**Test split** (1,272 tracks, 6 windows each, artists never seen in training):

| Run | Params | Window cos | Track cos | Top-10 overlap | Genre AP | Best epoch, training time |
|---|---|---|---|---|---|---|
| Teacher, 6 windows (the ceiling) | 73.6 M | 1 | 1 | 1 | 0.285 | |
| LAION CLAP, every window (the app's other text model) | | | | | 0.197 | |
| Mean training vector (the floor) | | 0.709 | 0.769 | 0.007 | 0.136 | |
| MFCC mean/std + ridge | | 0.738 | 0.798 | 0.063 | 0.187 | |
| `mfcc40-mlp` | 0.30 M | 0.752 | 0.820 | 0.069 | 0.208 | 4, 1 min |
| **`cnn4-small-64`** | **0.23 M** | 0.851 | 0.911 | 0.169 | **0.300** | 5, 8 min |
| `cnn4-64` | 0.65 M | **0.857** | **0.916** | **0.189** | 0.296 | 5, 18 min |

Genre AP against the teacher and LAION, paired bootstrap over test tracks (500 resamples, `evaluate.py --bootstrap`):

| Student | minus teacher | minus LAION |
|---|---|---|
| `cnn4-small-64` | +0.014 (95% interval -0.005 to +0.031) | +0.103 (+0.082 to +0.125) |
| `cnn4-64` | +0.009 (-0.008 to +0.025) | +0.098 (+0.078 to +0.120) |
| `mfcc40-mlp` | -0.079 (-0.101 to -0.058) | +0.011 (-0.010 to +0.029) |

**Learning curve** (`cnn4-small-64`, nested subsets of the training tracks):

| Training tracks | Val window cos | Test top-10 overlap | Test genre AP |
|---|---|---|---|
| 500 | 0.829 | 0.149 | 0.277 |
| 1,000 | 0.833 | 0.161 | 0.298 |
| 1,500 | 0.840 | 0.169 | 0.300 |

**What it means:**

1. **For genre and description search, a 1 MB student matches the teacher:** `cnn4-small-64` is within noise of
   the 6-window teacher (interval includes 0) and clearly above LAION, at about a third of the teacher's CPU time
   per track (0.96 vs 2.79 CPU-s, Phase 0) and ~315 MB less memory.
2. **Raw cosine flatters:** the mean vector alone gets 0.71, because the teacher's vectors share a large common
   direction. The useful range is 0.71 to 1, and top-10 overlap and genre AP are the informative numbers.
3. **Seeing the spectrogram is what matters:** the CNNs beat the models that only see MFCC averages on every
   metric. The bigger CNN is slightly more faithful (top-10 overlap 0.19 vs 0.17) but not better at genre search.
4. **Closest matches are the open question:** the students' 10 nearest tracks share only 1.7-1.9 with the
   teacher's. That says they differ, not that they are worse: whether they sound right is a listening test.
5. **Data:** genre AP stops rising at ~1,000 tracks; fidelity still rises slowly (+0.007 cosine, +0.008 overlap per
   500 tracks). More tracks alone would help closest matches only a little.
6. **Underfitting, not overfitting:** training loss ends near the validation level (training cosine ~0.84), and
   validation bounces between epochs (fixed learning rate). Next levers: a learning-rate schedule, a somewhat larger
   CNN, centring the targets (subtract the mean direction so the loss works on what distinguishes tracks), and the
   128-band `mnv3s-128`.

**Free-text queries beyond genre tags** (`evaluate.py --queries`): 59 queries, the prompt list of
[../../allmusiccaps_prompts.md](../../allmusiccaps_prompts.md) (genres, other dance music, far from the library,
mood, limits) and the 5 long descriptions of the brief. For each query, the teacher's ranking of the 1,272 test
tracks against each student's (same text vector) and, as a yardstick for how much two different good models agree,
LAION's (its own text encoder). Raw numbers:
[../results/2026-11-25_distill_query_agreement.json](../results/2026-11-25_distill_query_agreement.json).

| Agreement with the teacher's ranking | `cnn4-64` | `cnn4-small-64` | LAION CLAP |
|---|---|---|---|
| Spearman over all tracks | 0.75 | 0.74 | 0.18 |
| Top-50 overlap | 0.39 | 0.37 | 0.13 |
| Top-10 overlap (chance 0.008) | 0.21 | 0.18 | 0.08 |
| Long descriptions only: Spearman / top-50 | 0.79 / 0.36 | 0.78 / 0.34 | 0.16 / 0.17 |

- **Long, compound queries work as well as short ones:** the text side is the teacher's own encoder, so the
  student only has to place tracks in the space, and it does so as consistently for long descriptions.
- **The order agrees, the top of the list less:** ~2 of the top 10 and ~19 of the top 50 are shared. Top-k overlap
  is harsh when many tracks score almost the same: `old-school jungle with chopped amen breaks and reggae bass` has
  top-10 overlap 0 at Spearman 0.86 (many near-equal jungle tracks reshuffle).
- **Agreement is not relevance:** whether the student's top 10 is worse, or just different, needs a listening test
  (blind: both top lists shuffled together, rated per track).

**Limits:** one seed per model, so run-to-run variation is not measured; the bootstrap covers the choice of test
tracks, not of the 27 prompts; one library and one DJ's tags; the student learned from this library's sound, so
other users' libraries may suit it less (Phase 2 needs a check on other music before shipping).

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
| [prepare_data.py](prepare_data.py) | Phase 1 data: artist-aware split, log-mel cache and matching teacher vectors |
| [train.py](train.py) | Phase 1: baselines and students, early stopping, one MLflow run each, ONNX of the best weights |
| [evaluate.py](evaluate.py) | Fidelity and genre-AP metrics; `python evaluate.py` logs the reference runs, `--bootstrap RUN...` the paired bootstrap, `--export-json` the results file |
| [phase1_eval.ipynb](phase1_eval.ipynb) | Charts and tables from MLflow: all runs, genre AP, training curves, per-label AP, learning curve, cost vs quality (kernel: the venv, registered as `venv-distill`) |
| [requirements.txt](requirements.txt) | Pinned versions of the venv |

**MLflow:** runs are stored in `.research_cache/distill/mlflow.db` (experiments `distill-speed` for Phase 0,
`distill-train` for Phase 1). To browse them, from the repo root:

```
.research_cache\venv-distill\Scripts\mlflow ui --backend-store-uri sqlite:///.research_cache/distill/mlflow.db
```

then open http://127.0.0.1:5000. `benchmark_speed.py --log-json <results.json>` logs an earlier benchmark.

Outputs: `.research_cache/distill/` (git-ignored: ONNX files, feature cache, MLflow store) and one small JSON
per run in [../results/](../results/).

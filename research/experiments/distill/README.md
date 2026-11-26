# AllMusicCaps distillation: a small audio encoder for CPU-only machines

**Question:** can a small network, fed cheap log-mel features, put tracks into the AllMusicCaps CLAP audio space
well enough for the map, closest matches and free-text search, at a fraction of the CPU cost? The original text
encoder stays, so typed queries keep working. Background and literature: the
[distillation brief](../../../docs/research/allmusiccaps_distillation_brief.md), the
[Phase 1 assessment and Phase 2 plan](../../../docs/research/allmusiccaps_distillation_phase2.md) and
[allmusiccaps_clap.md](../../../docs/research/allmusiccaps_clap.md).

**Why:** on a GPU the teacher is already fast (~24 ms per 10 s window on DirectML). On the CPU it takes
112-217 ms per window, and the app embeds every window, so 4-8 s per 6-minute track. Users without a GPU carry
that load.

## Phases

| Phase | Question | Status |
|---|---|---|
| 0 | Is a student really cheaper end to end (decode + features + model)? Random weights: speed does not depend on training | done 2026-11-25: yes, see results |
| 1 | How close can a trained student get? Teacher targets: the 130,705 window vectors already in the app's cache (3,380 tracks), no teacher runs needed | done 2026-11-25: on genre search a 1 MB student matches the teacher; closest matches differ, see results |
| 2 | Make the student better where it is weak (closest matches): a clean split, sanity checks, longer training, then losses ([plan](../../../docs/research/allmusiccaps_distillation_phase2.md)) | in progress: split, overfit test, 40 epochs, seed noise, a look inside the space and a learning-rate schedule done 2026-11-25, see results |
| 3 | Best student to ONNX (int8?), app integration as its own model entry | after 2 |

## Phase 0 results, 2026-11-25

**Setup:** Intel i5-10300H (4 cores, 8 threads), 34 GB RAM, Windows 11; onnxruntime-directml 1.24.4, CPU provider,
the app's session options; 10 random library tracks from the teacher cache (70 minutes, 426 windows, seed 1),
decoded with the app's decoder; batch 8; students with random weights. One run, laptop in normal use (VS Code
open), so the run-to-run variation is not measured. Raw numbers:
[../../results/2026-11-25_distill_phase0_speed.json](../../results/2026-11-25_distill_phase0_speed.json).

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

**Trained weights, same benchmark** (after Phase 1, [../../results/2026-11-25_distill_speed_trained.json](../../results/2026-11-25_distill_speed_trained.json)): `cnn4-small-64` trained runs at 30.9 ms per window (random weights: 30.3) and 1.01 s / 0.99 CPU-s per 6-minute track with 6 windows; the teacher on every window, 4 threads, 6.31 s / 22.7 CPU-s in the same run. Speed does not depend on training, as assumed: 6.2x faster and 23x less CPU time than the app today.

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
[../../results/2026-11-25_distill_phase1.json](../../results/2026-11-25_distill_phase1.json); charts:
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
[../../data/allmusiccaps_prompts.md](../../data/allmusiccaps_prompts.md) (genres, other dance music, far from the library,
mood, limits) and the 5 long descriptions of the brief. For each query, the teacher's ranking of the 1,272 test
tracks against each student's (same text vector) and, as a yardstick for how much two different good models agree,
LAION's (its own text encoder). Raw numbers:
[../../results/2026-11-25_distill_query_agreement.json](../../results/2026-11-25_distill_query_agreement.json).

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

## Phase 2, first steps, 2026-11-25

Following the [Phase 2 plan](../../../docs/research/allmusiccaps_distillation_phase2.md): fix the evaluation first,
then the sanity checks a training pipeline should pass, then the cheapest lever. Raw numbers:
[../../results/2026-11-25_distill_phase2_first_steps.json](../../results/2026-11-25_distill_phase2_first_steps.json)
(MLflow runs tagged `phase: 2`).

**1. Split (E00).** Phase 1's validation set was the test artists' other tracks: it shared 200 artists with the
test set, and early stopping and model choice were made on it. Now no artist is in two of train, val and test
(`prepare_data.py --split-only`: only the manifest changes, the cached windows stay; the Phase 1 manifest is kept as
`manifest-phase1.parquet`). Test: unchanged, 1,272 tracks (so all numbers stay comparable). Holdout (unused): the
608 old validation tracks. Validation: a seeded 20 % of the other artists, 301 tracks (16 windows each, like
training). Training: 1,199 tracks. Known limit, accepted: artists are matched by name only, so collaborations
("A & B" vs "A") are not linked (~190 training tracks share a name with a test artist that way).

**2. Overfit test (sanity check).** `cnn4-small-64` on 50 tracks (800 windows), 200 epochs, no early stopping, with
`--eval-train` (training cosine measured in eval mode, comparable with validation): training cosine 0.60 → **0.946**,
validation ~0.71 (best 0.738; mean baseline 0.68). It learns its training data: the pipeline (inputs, targets,
loss, optimiser) is sound, and Phase 1's plateau (train ≈ val ≈ 0.84) is a modelling question, not a bug. Side
finding: 50 tracks already give genre AP 0.273 (teacher 0.285), so genre AP barely separates students; neighbour
agreement (top-10 overlap 0.126) does.

**3. Baseline on the new split, and the seed noise.** Phase 1 settings (at most 10 epochs, patience 3), three seeds;
then one run of 40 epochs without early stopping:

| Run | Best epoch | Test window cos | Top-10 overlap | Genre AP |
|---|---|---|---|---|
| Phase 1 (1,500 tracks, old validation) | 5 | 0.851 | 0.169 | 0.300 |
| New split, seed 0 / 1 / 2 | 8 / 8 / 9 | 0.855 / 0.854 / 0.857 | 0.192 / 0.194 / 0.197 | 0.293 / 0.297 / 0.293 |
| **New split, 40 epochs** (seed 0) | 39 | **0.865** | **0.223** | 0.285 |

- **Seed noise is small:** the three seeds span 0.0025 in window cosine and 0.005 in top-10 overlap. Measured once,
  this is the yardstick for later runs; a difference near it needs more seeds, a larger one doesn't.
- **The student was undertrained:** validation kept improving up to epoch 39 (0.816 at epoch 8 → 0.826), and
  neighbour agreement rose 0.194 → 0.223, about 6x the seed range. Early stopping on the old validation set had
  stopped it at epoch 5. The training-validation gap opens slowly (0.02 → 0.05), and validation jumps between epochs
  under the fixed learning rate: a learning-rate schedule is the next cheap step.
- **Genre AP fell to exactly the teacher's 0.285** as fidelity rose: the earlier "above the teacher" was most likely
  the smoother, coarser space of a less faithful student, not better search.
- Phase 1 vs the new split mixes two changes (validation set and 20 % fewer training tracks), so it is not a clean
  comparison; 10 vs 40 epochs is.

**4. A look inside the space** ([space_diagnostics.ipynb](space_diagnostics.ipynb), CPU, no training; test set,
baseline student `cnn4-small-64-n1199`):

- **Anisotropy:** two random test windows have cosine 0.52; a window and the training mean direction 0.71. Much of
  the raw cosine is free: centred (training mean subtracted) the student scores 0.68 per window (raw 0.855), the
  mean baseline 0.09 (raw 0.708).
- **The teacher uses few directions:** 5 principal components hold 50 % of the variance, 16 hold 80 %, 62 hold 95 %;
  participation ratio 12.8 of 512.
- **Coarse kept, fine missing:** per teacher component, the student's coordinate correlates with the teacher's at
  ρ² 0.50 for components 1-8 (71 % of the variance), 0.12 for 9-32 (18 %) and 0.05 for 33-128 (8 %); where it is
  unsure it is also shrunk (spread 0.4-0.5 of the teacher's). The neighbours need the fine part: the teacher itself,
  cut to its first 16 components, keeps only 0.77 of its own top-10 neighbours (4 components: 0.34). This explains a
  good genre score with weak neighbour agreement, and points at losses on the relations between tracks (relational
  distillation) rather than more of the same loss.
- **Relations:** the correlation of all track-pair similarities with the teacher's is 0.84 (50-track student:
  0.68); linear CKA 0.89.
- **Error analysis:** per-window agreement depends mostly on how close the window is to the training data in the
  teacher's space (correlation 0.60; 0.48 for the least familiar tenth vs 0.85 for the most familiar), little on
  loudness (0.18), and dips around 7/12 of the track (often the main breakdown in dance music). Variation is half
  between tracks, half within. By first genre tag: drum & bass 0.80, breakbeat 0.63, electro break and "electronic"
  about 0.58 (centred cosine). The misses are mostly music unlike anything in training: a data-coverage limit.
- **Duplicates:** 324 songs exist more than once (651 of 3,380 files; one folder copied into another). None leaks
  (the only cross-split copies pair test with the unused holdout). Copies are identical for the teacher, so a test
  track's copy is its nearest neighbour for both models: the student "finds the nearest" 100 % for tracks with a
  copy vs 30 % without. Top-10 overlap moves by under 0.01 with one copy per song (0.192 → 0.186), so the
  comparisons above stand.

**5. Learning-rate schedule (E02).** `train.py --schedule cosine`: the learning rate falls from 3e-4 to 0 over the
40 epochs (a step per batch); the only change from the 40-epoch run above (same seed, same selection). Raw numbers:
[../../results/2026-11-25_distill_phase2_lr_schedule.json](../../results/2026-11-25_distill_phase2_lr_schedule.json).

| 40 epochs, seed 0 | Test window cos | Track cos | Window cos, 5th pct | Top-10 overlap | Genre AP | Validation, last 10 epochs |
|---|---|---|---|---|---|---|
| Constant 3e-4 | 0.865 | 0.925 | 0.631 | 0.223 | 0.285 | 0.807-0.826 |
| Cosine 3e-4 → 0 | 0.869 | 0.931 | 0.638 | 0.222 | 0.289 | 0.827-0.833 |

Steadier (the last epochs settle instead of jumping, so the result no longer depends on the epoch it stops at) and
slightly more faithful per window and per track, but the **neighbours did not move** (−0.002, within the seed range
of 0.005). Training kept learning to the end (training cosine 0.88, as with the constant rate). So the neighbour gap
is not an optimisation problem; the cosine schedule stays as the recipe.

**Next** (in `docs/BACKLOG.md`; the user's focus is model structure): temporal modelling instead of the plain time
average and/or 128 mel bands; relational distillation with model choice on validation top-10 overlap; a data pilot on
FMA medium (30 s clips are enough to train on; the test stays on whole tracks). Listening test (E11) before any claim
about quality.

## Phase 2, model structure, 2026-11-26

Why: after its 4 conv blocks the CNN has one frame per 160 ms, each seeing ~0.46 s (about a beat), and then takes
the mean and std over time: a "bag of beats" that is blind to the order of beats, bars and phrases, while the
teacher (a transformer) relates the whole 10 s window. The learning-rate schedule (section 5) showed the neighbour
gap is not optimisation. Three students, one change each from `cnn4-small-64`, all on the section 5 recipe (40 epochs,
cosine schedule, seed 0, best epoch on validation cosine):

- `cnn4-small-64-tcn`: 4 residual, dilated (1, 2, 4, 8), depthwise-separable 1-D convolutions over time after the CNN;
  each frame then sees ~5.3 s (2-3 bars). +69 k parameters.
- `cnn4-small-64-attn`: attentive statistics pooling (a learned weight per frame and channel) instead of the plain
  mean/std. Still order-blind: it can learn which moments count, not what follows what. +17 k parameters.
- `cnn4-small-128`: 128 mel bands instead of 64 (`prepare_data.py --mels 128`, 9 GB cache, checked row for row
  against the 64-band cache).

Both new parts start at zero, so each new student begins as exactly the plain one (checked) and only uses the new
part if it helps. Validation top-10 overlap is now logged per epoch (watched, not used to choose the epoch).

| Seed 0 | Test window cos | Track cos | Top-10 overlap | Genre AP | Val top-10 | Train cos | Train time | CPU ms/window |
|---|---|---|---|---|---|---|---|---|
| Plain (`cnn4-small-64`, section 5) | 0.869 | 0.931 | 0.222 | 0.289 | 0.389 | 0.878 | 32 min | 35.0 |
| Attentive pooling | 0.870 | 0.932 | 0.223 | 0.288 | 0.405 | 0.883 | 37 min | 38.1 |
| 128 mel bands | 0.871 | 0.932 | 0.218 | 0.286 | 0.399 | 0.875 | 78 min | 44.2 |
| **Temporal blocks** | **0.876** | **0.939** | **0.230** | 0.290 | **0.437** | **0.917** | 36 min | 38.4 |

CPU: `benchmark_speed.py`, 1 thread, 10 library tracks
([../../results/2026-11-26_distill_structure_speed.json](../../results/2026-11-26_distill_structure_speed.json));
per 6-minute track with 6 windows 1.14 s plain, 1.18 s temporal, 1.23 s with 128 bands (0.9 s of it decoding).

- **Only temporal context moves anything:** +0.008 top-10 overlap on test, +0.007 window cosine; attentive pooling and
  128 bands are within the seed range (0.005). The student lacks context over time, not frequency detail or a
  smarter average. The temporal blocks cost +3 ms per window on the CPU.
- **Validation overstates the gain** (+0.048 vs +0.008 on test). Not because the test music is less familiar: test
  windows are slightly closer to the training data than validation windows (median closest-training cosine 0.954 vs
  0.942). The two numbers measure different things: validation picks 10 of 301 tracks from 16-window track vectors,
  test 10 of 1,272 from 6 windows. Measured alike (validation with 6 windows; test in random 301-track pools) the plain
  student scores 0.365 on both; the temporal one 0.396 / 0.381 (+0.031 / +0.016). Raw validation and test top-10
  numbers must not be compared directly.
- **The temporal student fits its training data much better** (training cosine 0.917 vs 0.878) than it generalises
  (validation +0.009): the gap grew from 0.045 to 0.075. It has capacity that 1,199 tracks do not fill, which is
  the case where more data helps; the learning curve below measures it.
- It is also clearly more robust to low-bitrate audio (side check below).

## Side check: audio quality, original vs 64 kbps MP3, 2026-11-26

Question (user): free training sets are often low quality; how much does audio quality change the log-mel input and
the vectors? [codec_robustness.py](codec_robustness.py): 98 test tracks (sources median 259 kbps) re-encoded to
64 kbps MP3 (libmp3lame via PyAV); the app's decoder keeps the copy aligned to the sample, so the same windows hold the
same moments. MLflow experiment `distill-robustness`; raw numbers:
[../../results/2026-11-26_distill_codec_robustness.json](../../results/2026-11-26_distill_codec_robustness.json).

| Original vs 64 kbps copy | Track cosine | Finds its own original first | Top-10 neighbours kept |
|---|---|---|---|
| Teacher | 0.982 | 96 % | 64 % |
| Student, plain (`cnn4-small-64`, cosine recipe) | 0.948 | 54 % | 31 % |
| Student, temporal (`cnn4-small-64-tcn`) | 0.975 | 78 % | 51 % |

- The codec changes the log-mel only above ~5 kHz: below 4 kHz ≈ 0.9 dB on average, then −7 dB at 7.6 kHz, −14 dB at
  9.2 kHz, −23 dB at 10.5 kHz (the top band). At 64 kbps the cut-off falls inside the mel range; at typical bitrates
  (128 kbps and up) it should lie above the 12 kHz that the 24 kHz conversion keeps for every track (not measured).
- The teacher still recognises the track, but a third of its top 10 changes (neighbours 5-15 are near-ties). The
  students drift more (plain 2.9x the teacher's drift, temporal 1.4x) and agree less with the teacher on the copies
  (plain 0.855 → 0.815). The temporal student is clearly the more robust one.
- Exact duplicates in the library (25 of the 98 sampled tracks have one in the test pool) count as the track itself;
  counted as misses they had made the teacher look like 86 % instead of 96 %.

**Closed (user, 2026-11-26):** DJs play good-quality files, and the pipeline already converts every track the same
way (24 kHz), so no codec augmentation or low-pass variants. If low-bitrate data (e.g. FMA) is used for training,
check its bitrates first: below ~128 kbps the codec reaches into the bands the model uses.

## Setup

A separate venv, so nothing here changes the app's `.venv` or the exe (torch 2.8 CUDA for training on the
4 GB GPU; onnxruntime-directml 1.24.4, the app's runtime, for fair speed numbers):

```
uv venv .research_cache\venv-distill --python 3.12
uv pip install --python .research_cache\venv-distill\Scripts\python.exe torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu126
uv pip install --python .research_cache\venv-distill\Scripts\python.exe -r research\experiments\distill\requirements.txt
```

If C: is short of space, point `UV_CACHE_DIR`, `TMP` and `TEMP` at a folder on another drive first.

The feature cache (`.research_cache/distill/data`, 13 GB with `mel128.npy`) can live on another drive behind a
directory junction, so every path in the code stays the same. On the development machine it is on D: (2026-11-26):

```
New-Item -ItemType Junction -Path .research_cache\distill\data -Target D:\SongSelector-research\distill\data
```

## Files

| File | What |
|---|---|
| [common.py](common.py) | Paths, the teacher's contract (24 kHz, 10 s windows, 512-d), the app's decoder and windowing, reading the teacher cache |
| [students.py](students.py) | Student networks with the log-mel front end inside; `python students.py` exports them (random weights) to ONNX and checks ONNX against PyTorch |
| [benchmark_speed.py](benchmark_speed.py) | Phase 0: teacher vs students on the CPU, each (model, threads) in a fresh process |
| [prepare_data.py](prepare_data.py) | Data: artist-disjoint train / val / test split, log-mel cache and matching teacher vectors; `--split-only` re-splits the existing cache |
| [train.py](train.py) | Phase 1: baselines and students, early stopping, one MLflow run each, ONNX of the best weights |
| [evaluate.py](evaluate.py) | Fidelity and genre-AP metrics; `python evaluate.py` logs the reference runs, `--bootstrap RUN...` the paired bootstrap, `--export-json` the results file |
| [codec_robustness.py](codec_robustness.py) | Side check: teacher and students on originals vs low-bitrate MP3 copies (vectors, neighbours, log-mel per band) |
| [phase1_eval.ipynb](phase1_eval.ipynb) | Charts and tables from MLflow: all runs, genre AP, training curves, per-label AP, learning curve, cost vs quality (kernel: the venv, registered as `venv-distill`) |
| [requirements.txt](requirements.txt) | Pinned versions of the venv |

**MLflow:** runs are stored in `.research_cache/distill/mlflow.db` (experiments `distill-speed` for Phase 0,
`distill-train` for training runs, `distill-robustness` for the audio-quality check, `distill-smoke` for smoke runs).
Each run has a `question` tag saying what it was for: in `distill-train` `reference` (teacher, LAION, trivial
baselines), `architecture` (Phase 1), `learning-curve`, `sanity` (overfit test), `seeds` (noise), `recipe` (epochs,
learning-rate schedule), `structure` (Phase 2 model structure). In the UI, filter with `tags.question = 'seeds'` or
add the tag as a column; `train.py --question <name>` sets it on new runs. To browse them, from the repo root:

```
.research_cache\venv-distill\Scripts\mlflow ui --backend-store-uri sqlite:///.research_cache/distill/mlflow.db
```

then open http://127.0.0.1:5000. `benchmark_speed.py --log-json <results.json>` logs an earlier benchmark.

Outputs: `.research_cache/distill/` (git-ignored: ONNX files, feature cache, MLflow store) and one small JSON
per run in [../../results/](../../results/).

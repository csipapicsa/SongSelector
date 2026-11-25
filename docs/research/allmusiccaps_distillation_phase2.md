# SongSelector — AllMusicCaps distillation: Phase 1 assessment and Phase 2 plan

**Date:** 2026-11-25  
**Purpose:** Technical handoff to a coding LLM. Extend the existing implementation rather than rewrite it.  
**Related specification:** [allmusiccaps_distillation_brief.md](allmusiccaps_distillation_brief.md)  
**Source PRs:** [#78](https://github.com/csipapicsa/SongSelector/pull/78), [#79](https://github.com/csipapicsa/SongSelector/pull/79).

## 1. Objective

Train a lightweight local audio encoder that maps a mel-spectrogram (or MFCC representation) into the original AllMusicCaps audio embedding space, preserving compatibility with its frozen text encoder. Prioritize actual semantic music search and end-to-end CPU throughput over parameter count alone. Teacher embeddings are generated offline and cached. No human annotations are necessary for basic distillation, but independent relevance labels/listening judgments are necessary to establish actual search quality.

## 2. Phase 1 results (reported in previous review)

These figures are transcribed from the earlier conversation's PR assessment, not independently re-extracted in this handoff. Verify against current PR artifacts, commit hashes, metric definitions and split manifests before treating them as authoritative. Do not silently change the baseline.

Reported 1,500 training tracks, 1,272 test tracks, no train/test artist overlap.

| Model | Parameters | Track cosine | Audio top-10 overlap | Genre AP |
|---|---:|---:|---:|---:|
| AllMusicCaps teacher | 73.6M | 1.000 | 100% | 0.285 |
| LAION CLAP | — | — | — | 0.197 |
| Mean teacher embedding | — | 0.769 | 0.7% | 0.136 |
| MFCC40 + MLP | 300K | 0.820 | 6.9% | 0.208 |
| CNN4-small-64 | 230K | 0.911 | 16.9% | 0.300 |
| CNN4-64 | 650K | 0.916 | 18.9% | 0.296 |

Free-text search, reportedly 59 queries:

| Metric | Small CNN | Larger CNN | LAION CLAP |
|---|---:|---:|---:|
| Spearman rank correlation with teacher | 0.74 | 0.75 | 0.18 |
| Top-50 overlap | 37% | 39% | 13% |
| Top-10 overlap | 18% | 21% | 8% |
| Long-description rank correlation | 0.78 | 0.79 | 0.16 |

Reported six-minute-track timing (Intel i5-10300H; verify backend, thread count, and timing protocol):

| Pipeline | Seconds |
|---|---:|
| Teacher, all windows | 5.87 |
| Teacher, 6 windows | 1.60 |
| Small CNN, 6 windows | 0.96 |
| Audio decoding alone | 0.81 |

## 3. Assessment

- Strong feasibility signal: a 230K-parameter CNN (roughly 320x fewer parameters than 73.6M) reproduces much of the teacher's ranking behavior with a small training corpus. Parameter ratio is not a measured latency ratio.
- Genre AP is comparable in point estimates, but superiority/equivalence is not established without uncertainty estimates and a prespecified margin. Genre labels do not establish nuanced music search quality.
- High raw cosine is partly explained by the mean-vector baseline (0.769): the teacher space has a substantial shared direction. The neighbor overlap of 16.9–18.9% and free-text top-10 agreement of 18–21% show substantial remaining errors. Inspect centered cosine, per-dimension variance, effective rank, and score/rank agreement.
- Same-window end-to-end speedup is ~1.67x (1.60/0.96), not the ~6.1x obtained against the all-window teacher. Both are useful comparisons but answer different questions. Decoding occupies much of the student's reported wall time, so more student capacity may be affordable. Rebenchmark rather than assume.
- Underfitting is a plausible hypothesis, not a diagnosis. Inspect train/validation curves, compare longer training and capacity, and check the information bottleneck in the student input and temporal pooling. Low test agreement could reflect overfitting, target/input mismatch, loss mismatch, or insufficient information rather than capacity.
- Reported validation/test artist overlap should be eliminated for a clean final benchmark. If previous test results have guided decisions, treat that set as development data and establish a new untouched test set. Repeat seeds and validate on another music collection.
- Research potential: a useful engineering contribution, possibly suitable for music information retrieval research if compared to existing approaches on independent data and real relevance outcomes. No novelty or publication claim established yet.

## 4. Candidate architectures

| Architecture | Role |
|---|---|
| CNN4-small-64 (230K) | Reproducible baseline |
| CNN4-64 (650K) | Reproducible larger baseline |
| Same CNN with 128 mel bins | Input-resolution ablation |
| MobileNetV3-Small / width-scaled MobileNet | Efficient general-purpose CNN, adapted to one-channel log-mel input and teacher-sized output |
| Residual CNN (~1–5M as a candidate budget) | Capacity and skip-connection experiment |
| EfficientAT MN variants (e.g. mn01_as, mn04_as, mn10_as, verify available checkpoints) | AudioSet-pretrained audio CNN, compare frozen feature regression, partial/full fine-tuning, and random initialization |

Parameter counts for new candidates depend on width, head and embedding dimensionality. Count actual trainable and total parameters, MACs if useful, and measure latency. EfficientAT is not a wholly separate family from MobileNetV3: its MN models are audio-adapted MobileNetV3 models trained with transformer distillation. The repository also includes Dynamic MobileNets. Use the official preprocessing for pretrained weights (verify checkpoint sample rate, mel bins, scaling, hop and normalization); the reference inference script uses 32 kHz and 128 mel bins. A 64-bin custom frontend may be a distribution shift. Do not use a pretrained classifier's class probabilities as the teacher embedding.

### What is underfitting?

A model fails to adequately learn even its training examples. In practice, training error stays high relative to an achievable baseline. It may be caused by low capacity, insufficient optimization, excessive regularization, or input features that discard needed information. If train error is low but validation error is high, overfitting is more likely. If both plateau high, check optimization and input/target alignment before assuming larger models are required.

## 5. Loss experiments

Let `t` denote the frozen teacher embedding, `s` the student prediction, and `q` a frozen teacher text embedding. Check exact checkpoint scoring, normalization and pooling first. Preserve the original retrieval interface; do not replace embeddings in the existing database with centered vectors.

### Baseline: direct cosine regression

`L_cos = mean(1 - cosine(s, t))`. Also report MSE and original-space cosine. Cache matched segments for teacher and student. Verify that the original teacher consumes the same underlying audio interval as the student's features; differing windows may make the target impossible to predict faithfully.

### Centering / residual prediction

Fit `mu = mean(t_train)` from training targets only, using the chosen teacher normalization convention. Train a raw residual head `r` to predict `t - mu` (e.g., residual MSE, optionally residual cosine with a norm-sensitive term). Reconstruct `s = normalize(mu + r)` at inference if original scoring uses normalized embeddings. Do NOT normalize the residual alone then add the mean: that discards its magnitude. Consider combining original-space loss with residual loss, and compare matched baselines. Centering is a hypothesis; it is an invertible translation, not automatically a cure for anisotropy. Do not fit mean/PCA/whitening on validation/test data.

### Relational knowledge distillation

For L2-normalized batch embeddings `S,T`, compute off-diagonal similarities `S @ S.T` and `T @ T.T`. Use mean squared differences or a row-wise KL ranking/distribution objective with tuned temperature. Combine with direct regression: `L = L_cos + lambda_rel * L_rel`. Exclude diagonals, avoid batches dominated by segments of the same track, optionally use a training-only memory bank. Compare several lambda values using development data. Batch size matters; gradient accumulation alone does not increase the number of pairwise comparisons in each batch.

### Text-aware distillation

Create diverse training prompts (genre, mood, rhythm, production, instrumentation, timbre, combinations, and hard contrasts); cache frozen text embeddings. Keep evaluation prompts independent, including paraphrase/concept holdouts. Match teacher similarity scores `T @ Q.T` to student scores `S @ Q.T` (MSE or appropriate ranking/distribution loss; confirm original scoring). Add `lambda_text * L_text` to the direct loss. Since this is a projection of embedding error, it emphasizes directions relevant to language queries rather than providing independent ground-truth supervision. Teacher biases may be inherited. If teacher cosine scores have little spread, inspect scaling and use query-wise rank-sensitive objectives. Evaluate real relevance separately.

### Combined objective

`L = L_cos + lambda_res * L_res + lambda_rel * L_rel + lambda_text * L_text` (only activate tested terms). Start with one change per run, then combine the best options. Log each raw/weighted loss and avoid choosing settings on the final test set.

## 6. Phase 2 experiment matrix

| ID | Experiment | Priority | Decision criterion |
|---|---|---|---|
| E00 | Audit splits, baseline data/preprocessing and teacher targets; create new test holdout | Essential | Reproducible, leakage-free evaluation |
| E01 | Repeat baseline with 3–5 seeds | High | Establish baseline variance |
| E02 | Longer training + LR schedule, checkpoint selection on validation | High | Does training loss and validation retrieval improve? |
| E03 | Centered residual prediction | Very high | Improve discriminative retrieval, not just raw cosine |
| E04 | 128 vs 64 mel bins, same architecture/training | High | Benefit vs feature and inference cost |
| E05 | Larger CNN / residual CNN / MobileNetV3 | High | Determine capacity–latency frontier |
| E06 | Relational loss | Very high | Improve audio neighbor agreement and rank metrics |
| E07 | Text-aware loss | Very high | Improve unseen prompt retrieval |
| E08 | Combine best settings | High | Demonstrate repeatable gains |
| E09 | Increase training corpus to 3K/5K/10K+ distinct tracks as feasible | High | Learning curve, diversity and generalization |
| E10 | External dataset validation | Essential | Robustness across collections and genres |
| E11 | Blind listening/relevance evaluation | Essential | True semantic retrieval performance |
| E12 | ONNX export, INT8 quantization | Later | CPU performance with acceptable quality change |
| E13 | EfficientAT frozen encoder + linear/MLP head, then fine-tuning, then matched scratch architecture | High | Value of audio pretraining under limited training data |

Suggested order: E00–E02, then E03/E06/E07 plus E04 and E13 (cheap frozen-feature baseline), then larger architectures and data scaling as indicated by results. Perform external/held-out testing after selecting models on validation data. A small budget can justify sequential screening rather than a full factorial grid.

## 7. Evaluation protocol

- Artist-disjoint train/validation/test partitions; group duplicate tracks, edits, remixes, aliases and overlapping windows where possible. Fit transforms on training only. External set should be independent. Record exact data manifest/checksum and seed. Preserve the old test set only for historical comparison.
- Track and window cosine, centered cosine (using train mean), residual norm/variance, teacher vs student similarity distribution. Compare constant mean and random baselines. Compute audio-to-audio recall/overlap@10/50, excluding the query itself; define candidate set consistently.
- Text-to-audio Spearman per query, top-k teacher overlap, and nDCG/AP/Recall where independent relevance labels exist. Report per-query category and performance on complex prompts. Teacher agreement is fidelity, not actual accuracy. Use identical candidates and correct matching text encoder for each model (including LAION).
- Use paired comparisons and bootstrap uncertainty at the query/artist or track cluster level as appropriate; multiple seeds. Do not infer statistical equivalence from non-significance.
- Human evaluation: blinded randomized comparisons of retrievals from teacher, student and alternative baseline; multiple raters if possible, common relevance rubric and agreement assessment; ensure listening is authorized.
- Efficiency: decode, resample, feature extraction, inference, aggregation, end-to-end wall clock, peak RAM, model size. Same windows vs same coverage/full-track comparisons; record CPU, threads, backend, batch size, warmup, median and p95. Profile seeking/partial decoding and caching only if quality/codec behavior is preserved.
- Record per-run config, commit hash, cache manifest, optimizer, trainable parameter count, seed, time, hardware and metrics. Export tables and plots automatically; MLflow optional if already used. Do not overwrite Phase 1 results.

## 8. Instructions for coding LLM

1. Inspect existing repository code and PRs before editing. Identify the teacher checkpoint, output dimension, scoring and aggregation, preprocessing, loss, dataset manifest and benchmark scripts. Verify every reported figure above.
2. Reuse existing abstractions and implement new student/loss options behind configuration. Write tests for shapes, cached target alignment, train-only centering, original-space reconstruction, off-diagonal losses, prompt split, and artist leakage. Check gradients and overfit a tiny subset as a sanity test.
3. Cache teacher vectors and text vectors once per versioned preprocessing configuration. For frozen EfficientAT, cache features if appropriate. No teacher required at deployed student inference.
4. Start with inexpensive runs suitable for the available ~4 GB GPU (verify hardware). Use small batches/AMP as appropriate, and be mindful of actual memory for relational loss. Save checkpoints and support resuming. Avoid broad architecture sweeps until baseline reproducibility is established.
5. Select based on validation semantic retrieval and end-to-end CPU budget, not raw cosine alone. Freeze final model choice before test evaluation. Preserve original text-embedding compatibility and update the embedding cache/model version to avoid mixing incompatible outputs without testing.
6. Verify rights for music datasets, teacher weights and any student release; do not assume noncommercial model licensing disappears with distillation. This is a research/engineering plan, not legal clearance.

## 9. Resources

- [SongSelector PR #78](https://github.com/csipapicsa/SongSelector/pull/78) and [PR #79](https://github.com/csipapicsa/SongSelector/pull/79)
- [AllMusicCaps repository](https://github.com/MTG/allmusiccaps), [checkpoint](https://huggingface.co/mtg-upf/allmusiccaps_all_layers) (the teacher used here: `allmusiccaps_all_layers`, not `allmusiccaps_sigmoid`)
- Howard et al. (2019), [Searching for MobileNetV3](https://arxiv.org/abs/1905.02244), [Torchvision documentation](https://docs.pytorch.org/vision/stable/models/mobilenetv3.html)
- Schmid et al. (2023), [Efficient Large-scale Audio Tagging via Transformer-to-CNN Knowledge Distillation](https://arxiv.org/abs/2211.04772), [EfficientAT repository](https://github.com/fschmid56/EfficientAT), [Low-Complexity Audio Embedding Extractors](https://arxiv.org/abs/2303.01879)
- [EfficientAT pretrained releases](https://github.com/fschmid56/EfficientAT/releases), [reference inference](https://github.com/fschmid56/EfficientAT/blob/main/inference.py)
- [AudioMuse-AI-DCLAP](https://github.com/NeptuneHub/AudioMuse-AI-DCLAP) — community music CLAP distillation precedent; verify implementation and license.
- [tinyCLAP](https://huggingface.co/fpaissan/tinyCLAP) — compact CLAP precedent.
- [FRILL](https://arxiv.org/abs/2011.04609) — mobile speech embedding distillation precedent.
- [Relational Knowledge Distillation](https://arxiv.org/abs/1904.05068) — general methodological reference (the proposed similarity-matrix loss is a related variant, not necessarily the paper's exact loss).

## 10. Open questions and assumptions

The reported results, architecture and compute figures are from the earlier PR review and were not reverified in this file. Actual teacher target normalization, dimensionality, dataset provenance, license, and current PR state need verification. New architecture sizes and experimental priorities are proposals, not measured outcomes. Underfitting and benefits of centering, relational loss, text-aware loss, and pretraining remain hypotheses. No exact target AP/overlap is promised; choose acceptance thresholds in advance based on intended use and a measured CPU budget.

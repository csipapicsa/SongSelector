# AllMusicCaps audio encoder distillation — research and implementation brief

**Purpose:** handoff to a coding LLM for iterative implementation, training, evaluation and CPU deployment.  
**Target application:** local semantic music search (SongSelector), including free-form descriptions and audio-to-audio search.  
**Status:** proposed experiments, not trained or validated. References checked selectively on 2026-11-25.

## 1. Objective

Train a lightweight student that maps inexpensive audio features (log-mel spectrograms or MFCC sequences) directly into the final audio embedding space of MTG AllMusicCaps. Keep the matching original text encoder unchanged. The user should not need the expensive teacher audio model at inference time. The student must preserve useful text-to-music rankings, not merely produce vectors of the correct size.

```
OFFLINE TRAINING
waveform ──> frozen AllMusicCaps audio encoder ──> cached target vector
    └─────> log-mel / MFCC ──> student ──> predicted vector ──> loss against target

LOCAL INFERENCE
music ──> lightweight feature extraction ──> student (ONNX CPU) ──> music index
query ──> original matching text encoder ──> query vector ──> similarity search
```

This is feature-based knowledge distillation / embedding regression / surrogate modelling. No paired captions or human labels are necessary for basic teacher imitation. Human relevance labels are desirable for independent evaluation. An alternative is to map a cheap pretrained audio embedding into the target space using ridge regression or an MLP. Log-mel and MFCC matrices are hand-engineered features rather than pretrained semantic embeddings; the student learns the nonlinear mapping from acoustic patterns to the teacher's abstract representation.

The mapping cannot recover information discarded by the input representation. Consequently, MFCC summary statistics are likely to lose rhythm, temporal structure and timbre detail. A log-mel sequence is a stronger starting point. Distillation can preserve some of the teacher's semantic behavior, but cannot guarantee identical results or remove teacher bias.

## 2. Teacher and relevant prior work

### Primary teacher: AllMusicCaps (MTG-UPF)

- Official repository: https://github.com/MTG/allmusiccaps
- Paper: https://arxiv.org/abs/2608.25244 (AllMusicCaps: Album Reviews as Complementary Supervision for Music CLAP)
- Example checkpoint: https://huggingface.co/mtg-upf/allmusiccaps_sigmoid
- Other variants: https://huggingface.co/mtg-upf/allmusiccaps_all_layers ; https://huggingface.co/mtg-upf/allmusiccaps_lejepa
- MTG model collection: https://huggingface.co/mtg-upf/collections
- OMAR-RQ audio backbone: https://github.com/MTG/omar-rq

AllMusicCaps uses OMAR-RQ audio representations and an MPNet-family text encoder; the models are trained using captions derived from professional album reviews. Select a checkpoint after checking retrieval quality and licensing. Use the official inference code to establish its actual sample rate, segment duration, audio and text projection dimensions, normalization, pooling, similarity function, and checkpoint-specific behavior. Do not assume it uses LAION's 512-dimensional space or its preprocessing. Pin the checkpoint and code revision; embeddings from different checkpoints should not be mixed.

### Closest implementation precedent: AudioMuse-AI-DCLAP

- https://github.com/NeptuneHub/AudioMuse-AI-DCLAP
- https://github.com/NeptuneHub/AudioMuse-AI/blob/main/docs/ALGORITHM.md
- Original LAION CLAP: https://github.com/LAION-AI/CLAP

The project distills a LAION CLAP audio tower to a roughly 7M-parameter student retaining its 512-dimensional space, targeting efficient music search. Its developers report around 5–6x faster processing on a Raspberry Pi 5. These are project-reported figures, not an AllMusicCaps benchmark. Inspect the repository for current frontend, EfficientAT architecture, training scripts, availability of training data, and export details before reusing code. Its weights cannot be assumed compatible with AllMusicCaps. Reuse the approach, not the output space.

### Academic references (priority order)

| Reference | Relevance | Link |
|---|---|---|
| Paissan & Farella (2024), tinyCLAP: Distilling Contrastive Language-Audio Pretrained Models | CLAP audio encoder compression and zero-shot sound classification; not evidence of identical music retrieval | https://www.isca-archive.org/interspeech_2024/paissan24_interspeech.pdf |
| tinyCLAP implementation/weights | Inspect teacher/student training and deployment | https://huggingface.co/fpaissan/tinyCLAP |
| FRILL: A Non-Semantic Speech Embedding for Mobile Devices (2021) | Direct representation distillation for mobile inference; Google reports >32x feature extraction speed and <2% average accuracy decrease on their speech tasks | https://research.google/blog/frill-on-device-speech-representations-using-tensorflow-lite/ ; https://arxiv.org/abs/2011.04609 |
| Ding & Lerch (2023), Audio Embeddings as Teachers for Music Classification | Pretrained audio features supervise low-complexity music networks; evaluates classification rather than exact CLAP retrieval | https://arxiv.org/abs/2306.17424 ; https://ismir2023program.ismir.net/poster_182.html |
| CDCLAP (2026), Efficient distillation framework for zero-shot audio event classification | Cross-modal distillation for efficient zero-shot audio classification | https://www.sciencedirect.com/science/article/pii/S0893608026012190 |
| EfficientAT | Efficient pretrained audio CNNs / MobileNet-style backbone candidates | https://github.com/fschmid56/EfficientAT |

Additional leads from our discussion (verify titles, methods and links before relying on them): S-SONDO https://arxiv.org/abs/2604.24933 and https://github.com/MedAliAdlouni/ssondo ; Distilling Efficient Audio Models using Data Pruning with CLAP https://pub.dega-akustik.de/DAS-DAGA_2025/files/upload/paper/149.pdf ; Multi-Distillation from Speech and Music Representation Models https://arxiv.org/abs/2506.07237 ; cross-dataset label alignment and zero-shot music emotion prediction https://arxiv.org/abs/2410.11522 . No AllMusicCaps-specific distilled implementation was established in our discussion; this is not a systematic novelty search.

## 3. Data and feature extraction

- Use legally accessible music audio; confirm licenses separately for training, redistribution of cached embeddings, student weights and commercial deployment. Public availability does not imply permission. Candidate sources to investigate: FMA (https://github.com/mdeff/fma), MTG-Jamendo (https://github.com/MTG/mtg-jamendo-dataset), MagnaTagATune (https://mirg.city.ac.uk/codeapps/the-magnatagatune-dataset). Include diverse music and electronic subgenres; avoid a dataset dominated by speech or generic sound effects.
- Split by track and preferably artist/album BEFORE segment generation. Detect duplicate recordings, remixes and near-duplicates across splits. Reserve an external collection if possible. Use a fixed manifest and seed; consider teacher training overlap when interpreting external evaluation.
- Start with 1k clips to debug, then 10k, 50k, 100k+ clips for learning curves. These are exploratory scales, not proven sample requirements. Report unique artists, tracks and total hours; many segments of one song are not independent evidence of diversity.
- Use identical time intervals for teacher and student. Begin with teacher-native clip duration; 10 seconds was an earlier illustrative suggestion, not a verified AllMusicCaps requirement. Test longer context only after the baseline works. For whole tracks evaluate multiple segments, average normalized embeddings and renormalize, or use the official teacher pooling if different. Compare like with like.
- Student frontend initial candidates: 64/128 mel bins, 20/40 MFCC coefficients, time sequence retained. A practical starting configuration is 25 ms window, 10 ms hop, power mel filterbank and log floor; make sample rate, FFT size, fmin/fmax, normalization and padding explicit. Consider teacher-native sample rate first, then lower rates as ablations. Compute normalization statistics from training only. MFCC can be derived from the same log-mel features, so it does not eliminate the mel computation.
- Cache final teacher outputs once in eval/inference mode, using the correct projection head and documented normalization. Preserve IDs, checkpoint revision, timestamps, source hash, feature parameters and dtype. Store vectors in NumPy memmap, sharded arrays or similar; manifest in Parquet. Use float32 initially; test float16 storage separately.
- Do not augment only the student with major changes to the sound unless deliberately testing invariance. Teacher targets must correspond to the input; regenerate targets for transformations that change semantics.

## 4. Experiment matrix

All experiments use the same splits and teacher target space. Initial model sizes below are design targets, not results.

| ID | Input | Model | Purpose |
|---|---|---|---|
| T | Waveform | Original AllMusicCaps | Teacher reference, latency and retrieval ceiling for imitation |
| B0 | None | Mean training embedding | Trivial collapse baseline |
| A | MFCC mean/std over time | Ridge regression | Cheap lower bound |
| B | MFCC mean/std | 2-layer MLP | Nonlinear summary-feature baseline |
| C | 20/40 MFCC sequence | Small temporal 1D CNN | Test compressed time-varying features |
| D | 64-bin log-mel | Small 2D CNN, ~0.5–2M params | First serious trainable baseline |
| E | 128-bin log-mel | MobileNetV3-Small | Better capacity with efficient depthwise convolutions |
| F | Log-mel | EfficientAT pretrained backbone + new projection | Transfer learning; inspect expected frontend and license |
| G | Frozen cheap music embeddings | Ridge then MLP | Cross-model embedding mapping alternative (MusiCNN, Discogs-EffNet or OpenL3) |
| H | Best student | ONNX FP32 then INT8 | Deployment and quantization ablation |

Alternative encoders: https://github.com/jordipons/musicnn ; https://essentia.upf.edu/models.html ; https://github.com/marl/openl3 . Benchmark their entire inference cost; a cheap mapping does not make an expensive source encoder cheap.

For D: try four convolutional blocks (channels 32, 64, 128, 256), batch normalization, SiLU/ReLU, progressive pooling, global mean or mean+std pooling, linear projection to teacher dimension D, and L2 normalization if consistent with teacher scoring. Avoid excessive time-axis pooling early. Compare parameter counts rather than assume a target size. For C use temporal conv blocks with receptive fields covering multiple beats.

## 5. Training objective

Let `t` be the frozen final teacher audio vector, `s` the student prediction, and `q` a matching teacher text vector. For cosine retrieval, normalize both audio outputs and text vectors using the teacher convention. If the teacher uses another scoring rule, preserve it and evaluate vector norms separately.

Start with `L_embed = mean(1 - cosine(s, t))`. For normalized vectors, squared L2 distance is proportional to cosine distance, so combining them adds little by itself. For raw vectors consider MSE and a norm penalty if norms matter.

Optional extensions, introduced one at a time:

- Relational distillation: `L_rel = MSE(S @ S.T, T @ T.T)` over a batch of normalized embeddings, optionally excluding diagonal. Helps preserve pairwise audio similarity.
- Text-aware distillation: cache diverse teacher text embeddings Q; use `L_text = MSE(S @ Q.T, T @ Q.T)` or KL on temperature-scaled teacher and student rankings. If official scoring is not cosine, adapt to it. Does not require true paired captions; queries are anchors.
- Total loss: `L = L_embed + lambda_rel * L_rel + lambda_text * L_text`; start with only embedding loss, tune weights on validation. Do not use test prompts for training or model selection. Include held-out paraphrases and combinations.

Example PyTorch core (assuming cosine scoring):

```python
import torch
import torch.nn.functional as F

def distill_loss(pred, target, q=None, w_rel=0., w_text=0.):
    s = F.normalize(pred.float(), dim=-1)
    t = F.normalize(target.detach().float(), dim=-1)
    loss = (1 - (s * t).sum(-1)).mean()
    if w_rel:
        loss = loss + w_rel * F.mse_loss(s @ s.T, t @ t.T)
    if w_text and q is not None:
        q = F.normalize(q.detach().float(), dim=-1)
        loss = loss + w_text * F.mse_loss(s @ q.T, t @ q.T)
    return loss
```

Initial training defaults: AdamW, learning rate 3e-4 (search 1e-4 to 1e-3), weight decay 1e-4, 20–50 epochs with early stopping, batch size 16–64 or whatever fits the 4GB GPU. Use mixed precision if supported, gradient accumulation for memory constraints (note it does not enlarge relational-loss batches automatically), deterministic split seeds, and checkpoint resume. Track validation retrieval as well as loss. These are suggested starting values, not optimized settings. Teacher extraction can run separately on a larger GPU; no teacher gradients or online teacher execution during student training.

## 6. Evaluation protocol

### Teacher fidelity

- Mean, median and lower-tail per-clip cosine similarity; compare with B0.
- Norm error if relevant; embedding covariance/effective rank to detect collapse.
- Audio-to-audio nearest-neighbor overlap at K=10/50, excluding self and duplicate tracks.
- Text-to-audio: for each held-out query, score the identical held-out track catalog using original teacher text embeddings against teacher and student audio vectors. Compute top-K overlap = intersection size / K, Spearman correlation of scores, and optionally nDCG using teacher-derived relevance. Report per-query and macro averages, not only pooled scores.
- Teacher fidelity is not true semantic relevance. Separately obtain human judgments or independently annotated query-track pairs; report Recall@K, mAP or nDCG where labels support them. Compare teacher and student on identical labels. Blind ratings if feasible.
- Evaluate by genre, recording quality, clip length, and rare/compound descriptors. Report variation across seeds and bootstrap intervals over queries/tracks as appropriate.

Example held-out query themes (keep separate from training anchors):

- Hypnotic, psychedelic dance music with rolling tribal percussion and a deep, restrained bassline.
- Dusty old-school breakbeats, spacious dub textures, and a slightly menacing late-night atmosphere.
- Progressive club music with slowly evolving pads and a driving syncopated groove.
- Warm, hazy, euphoric music with organic percussion and little vocal presence.
- Sparse mechanical rhythms, dark atmospheres and an evolving rather than an aggressive energy.

Include simpler genres, tempo, vocals, instrumentation, mood and contrasts. Assess whether the teacher itself handles these queries well before distilling.

### Efficiency

On the same CPU and thread count compare teacher vs student end-to-end: decoding, resampling, feature extraction, model execution and pooling. Report batch=1 and batch throughput, warm-up separately, median and p95 latency, real-time factor (processing seconds / audio seconds), peak RAM, artifact size, parameter count and hardware/software details. Separate query encoder latency from audio indexing. Check FP32 ONNX vs PyTorch parity, then INT8 accuracy/latency trade-off.

### Proposed decision criteria (adjust after baseline)

No guarantees. Initially seek >=5x end-to-end speedup, a small audio model (e.g. <=10M params), mean cosine >=0.85 and top-10 teacher retrieval overlap >=0.70. These are tentative engineering targets, not literature-established thresholds. Use quality/speed Pareto frontier and human relevance to choose the deployment model; do not reject a useful student solely for missing a cosine target.

## 7. Implementation roadmap for coding LLM

1. Inspect official teacher repo and model card; record exact API, revision, input shape, clip length, output dimension, scoring and licenses. Run audio/text smoke test; reproduce official similarity results where possible.
2. Inspect DCLAP and tinyCLAP. Determine what is genuinely reusable, including training availability and license compatibility. Do not blindly import LAION-specific preprocessing, projection or checkpoint.
3. Build immutable dataset manifest and group-disjoint splits; implement deterministic segment extraction and teacher cache with resume and validation. Verify teacher outputs from cached clips against fresh inference.
4. Implement common feature pipeline and baseline B0/A/B/D. Overfit a tiny subset first to detect alignment or dimension bugs. Evaluate on unseen tracks. Run learning curve with fixed test protocol.
5. Compare C/E/F/G as justified by results. Test relational and text-aware objectives on best baseline, one change per run. Log all configurations and artifacts.
6. Export best student to ONNX; use ONNX Runtime CPU, verify numerical parity, test static or dynamic quantization as supported (CNNs often benefit from static calibration). Benchmark on target Windows CPU; DirectML optional, not a requirement. Keep preprocessing identical between training and deployment.
7. Integrate into SongSelector with model/version metadata on every indexed vector. Do not mix teacher checkpoints or incompatible student versions silently; validate cross-version behavior before mixing teacher and student vectors in one index. Provide reindex path and keep original text model/projection matching target.

Suggested stack: Python, PyTorch, torchaudio or librosa, NumPy, scikit-learn, pandas/Parquet, ONNX Runtime, pytest, optional MLflow for experiment tracking. Prefer simple scripts and YAML configurations over heavy orchestration.

Suggested repo layout:

```text
configs/                  # teacher, frontend, model, train, eval settings
src/teacher.py            # pinned official API wrapper
src/features.py           # common feature extraction
src/data.py               # manifests, splitting, segment dataset
src/models.py             # student architectures
src/losses.py
scripts/build_manifest.py
scripts/cache_teacher.py
scripts/train.py
scripts/evaluate.py
scripts/benchmark.py
scripts/export_onnx.py
tests/                   # shape, split integrity, deterministic frontend, cache, parity
artifacts/                # ignored: weights, cache, reports
```

Deliverables per run: config, split manifest hash, seed, checkpoint, metrics JSON/CSV, per-query retrieval results, latency and memory table, and notes on failures. Add unit tests for input shapes, consistent segment IDs, no artist leakage, finite vectors, normalization, training/inference feature parity and ONNX parity. Do not commit music or large cached vectors into Git.

## 8. Open questions and limitations

- Which AllMusicCaps checkpoint is best for the intended complex electronic music queries? Confirm output dimension, preprocessing, pooling and exact text scoring before training.
- How much target information survives mel resolution, MFCC truncation, mono conversion and shorter clips? Empirical question.
- How many distinct tracks are required? No reliable AllMusicCaps-specific estimate yet.
- Can student and teacher embeddings be safely mixed in an index? Test rather than assume.
- A cheap audio encoder will not automatically accelerate the original text encoder; measure separately and cache repeated queries.
- Teacher imitation can transfer teacher mistakes; a high cosine score does not prove human relevance.
- License compatibility, training data availability, compute budget and actual CPU benchmark remain unresolved. No training has been run and no claimed speed/quality threshold is validated for this project.

**Instruction to the next LLM:** implement incrementally, first establish a verified teacher baseline and a reproducible cache; then train the small log-mel CNN and cheap MFCC baselines. Report measured results before proposing larger models. Never invent checkpoint API details or benchmark numbers. The central question is the minimum CPU cost required to retain useful AllMusicCaps semantic music retrieval.

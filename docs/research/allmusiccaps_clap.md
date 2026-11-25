# AllMusicCaps CLAP (MTG) vs LAION CLAP

Desk research, 2026-11-21; first hands-on checks 2026-11-22 (section *Hands-on, 2026-11-22* below). Sources: the model and dataset cards on
Hugging Face, the GitHub repo `MTG/allmusiccaps`, the OMAR-RQ paper (links at the end). The model card has **no
benchmark numbers**, and the paper (ISMIR 2026) was not found online, so every quality claim below is a hypothesis to
measure. Try it: [experiments/clap/allmusiccaps.ipynb](experiments/clap/allmusiccaps.ipynb).

## The question

The user's point: LAION CLAP is trained on sounds, not music; a music-trained CLAP should search a DJ library better.

- **True for the model the app ships.** `clap-htsat-unfused` (`core/embedding_models.py`) was trained on
  LAION-Audio-630K, which is mostly sound effects and general audio (Freesound, BBC Sound Effects, ...) with some
  music, plus AudioSet with captions made from its tags. Its captions describe sounds, not styles.
- **Not true for LAION as a whole.** LAION also released music-trained checkpoints (`larger_clap_music`,
  `music_audioset_epoch_15_esc_90.14.pt`). `larger_clap_music` collapsed in our setup on 2026-11-13 (every text and
  track got nearly the same vector, see [text_search_clap.md](text_search_clap.md)) and was dropped, never retried
  through the original `laion_clap` package.

## Side by side

| | LAION `clap-htsat-unfused` (in the app) | MTG `allmusiccaps_all_layers` |
|---|---|---|
| Audio encoder | HTSAT-tiny, 28 M parameters, trained on general audio | OMAR-RQ (`clap_omarrq_mp_small_music`, Conformer, 77.6 M parameters with the projection): self-supervised (masked token prediction, BEST-RQ style) on 330 k hours of music, then CLAP training on top |
| Text encoder | RoBERTa, trained with the audio side | `all-mpnet-base-v2` (sentence-transformers), **frozen** |
| Captions | Mostly sound descriptions; AudioSet tags turned into sentences | ~540 k (YouTube track, Discogs release) pairs with captions written by an LLM from AllMusic album reviews: style, mood, tempo, energy, instrumentation, production |
| Input | 48 kHz, 10 s windows | 24 kHz mono raw waveform, cut into 1,280-sample patches (53 ms) inside the network: no spectrogram at inference (the mel was only a pre-training target); 10 s windows in the README and MTG's evaluation code, any length works |
| Embedding | 512, cosine | 512, cosine |
| Runtime | ONNX, in the app | PyTorch: `amclap` package (lightning, gin-config, sentence-transformers <5.2, omar-rq ~0.2, torch >= 2.6). MTG publishes no ONNX, but both towers export cleanly (probe below) |
| File | 122 MB audio + 501 MB text (ONNX) | `model.ckpt` 296 MB; text encoder weights downloaded separately at construction |
| License | Apache 2.0 | Weights CC BY-NC-SA 4.0, code AGPL-3.0, dataset CC BY-NC-SA 4.0 (non-commercial research) |
| Published results | Yes (LAION paper) | ISMIR 2026 paper (arXiv:2608.25244), see *The paper* below |

Released variants (all OMAR-RQ + `all-mpnet-base-v2`; "Layers" is which encoder layers feed the output):

| Variant (`mtg-upf/allmusiccaps_<name>`) | Captions | Layers | Objective | Text encoder |
|---|---|---|---|---|
| baseline | baseline | last | InfoNCE | frozen |
| amcquotes / amcstruct | quotes / structured | last | InfoNCE | frozen |
| baseline_quotes / baseline_struct | baseline + quotes / struct | last | InfoNCE | frozen |
| layer6 | baseline + quotes | 6 | InfoNCE | frozen |
| **all_layers** | baseline + quotes | all (learned weighted sum) | InfoNCE | frozen |
| sigmoid | baseline + quotes | all | sigmoid | trained |
| lejepa / infonce_sigreg | baseline + quotes | all | LeJEPA | frozen |
| te_trained | baseline + quotes | all | InfoNCE | trained (60 k steps) |
| **te_trained_sigreg** | baseline + quotes | all | InfoNCE + SigReg | trained (60 k steps) |

The authors: *"te_trained_sigreg is the best overall model; all_layers is the frozen-TE recipe it builds on."*
Models with a trained text encoder overfit after ~40-80 k steps, hence the 60 k checkpoints.

## Why it could be better for this library

- **The audio side already knows music.** OMAR-RQ was trained on music only; MTG reports it best among open
  self-supervised models for music tagging (also chords, beats, pitch). CLAP training then mostly learns a projection.
  HTSAT had to learn music from mostly non-music audio.
- **The captions use a DJ's vocabulary.** The dataset sample has deep house, tech house, techno, breakbeat, e.g.
  *"A tech house track with deep minimal beats."* Discogs styles split electronic music finely; LAION's captions
  never mention a reese bassline.
- **All layers.** Middle layers of music models tend to hold timbre and rhythm, which matter for genre;
  `all_layers` uses all 12 instead of only the last one. Correction (2026-11-22, from the code): it is a plain mean of
  the 12 layers (`OMARRQ.layers = (0..11)` in `config.gin`, `.mean(axis=0)` in `amclap/clap_modules/omarrq.py`), not
  a learned weighting; then a mean over time frames and the projection.

## Caveats

1. **Test `te_trained_sigreg` too**, not only `all_layers` (the variant first looked at).
2. **Noisy labels.** One album review captions every track of the album, and an LLM wrote the captions. Drum and
   bass did not appear in the part of the 50-row sample we could read: its coverage is unknown.
3. **Frozen text encoder.** A general sentence model may not separate "reese" from "wobble"; probably why the
   trained-text-encoder variant wins.
4. **Integration cost.** Smaller than feared: the export works and runs on DirectML (*ONNX export probe* and
   *DirectML* below). Still open: int8 and the app-side model entry.
5. **License.** Non-commercial terms are workable for a free GPL tool that downloads models separately (as concluded
   for the other MTG models in [model_candidates.md](model_candidates.md)). Share-alike: our ONNX conversion on
   Hugging Face would be published under CC BY-NC-SA 4.0 with credit to MTG.

## Plan to settle it

Step 1 of [text_search_clap.md](text_search_clap.md) (precision of the top 10 per label) was never run, so there is
no number for LAION either. In order:

1. Done 2026-11-22: `amc-all-layers` and `amc-te-sigreg` in the shared model interface
   ([experiments/clap/benchmark_cpu.py](experiments/clap/benchmark_cpu.py)), extracted with
   [extract_embeddings.py](experiments/clap/extract_embeddings.py) in the Windows research venv (CUDA).
2. ~3 prompts per genre tag (DnB, breakbeat, ...), precision of the top 10 and average precision for LAION light,
   MS CLAP 2023 and the two MTG variants: the genre-tag section of
   [allmusiccaps.ipynb](experiments/clap/allmusiccaps.ipynb). Also the similarity-map question from the backlog:
   neighbour purity with the user's labels, CNN14 vs the MTG audio embedding.
3. It wins (step 2, 2026-11-22), so next: the ONNX export of `all_layers` (works, see the probe), DirectML (works,
   2.6x faster than LAION), int8, CPU time with sampled windows, then a model entry in the app. Publishing the conversion means
   CC BY-NC-SA 4.0 with credit to MTG: the user's call.

## Hands-on, 2026-11-22

Setup: `pip install amclap==0.1.0` into `.research_cacheenv-clap` (torch 2.7.1+cu118, transformers 4.57.6; the venv
gets sentence-transformers 5.1.2, the system Python keeps 5.6). Laptop GPU with 4 GB (CUDA), fp32.

- **Loads and runs, no collapse.** Both `all_layers` and `te_trained_sigreg`: 512-d outputs, text-to-text cosines
  spread from -0.03 to 0.49 over four genre prompts (LAION's music model gave ~1.0 everywhere). The trained text
  encoder of `te_trained_sigreg` really loads: its weights equal the checkpoint's and differ from stock mpnet (the
  sentence-transformers >= 5.2 trap the authors warn about).
- **Speed (GPU):** batch of 8 x 10 s in ~165 ms, about 20 ms per window. Extraction of the test set is bound by
  decoding: 1.7 s per track for both models together.
- **Test set:** grown to 1,408 tracks (rating 4-5 with a colour) since the LAION / MS run (990); the notebook compares
  on the tracks every model has.

### Genre-tag retrieval: the MTG models win

Run 2026-11-22 with the genre-tag section of [allmusiccaps.ipynb](experiments/clap/allmusiccaps.ipynb). Data: the
990 test-set tracks that all four models have (rating 4-5 with a colour), of which 744 carry a genre tag; labels from
the DJ's own `genre` tags (9 labels with at least 5 tracks). Every 10 s window embedded, track = mean of the
normalised windows. 27 prompts (3 styles x 9 labels), written before any result was seen. Metric: average precision
(AP) of the whole ranking per prompt, then the mean; chance is the share of tagged tracks with the label.
Per-prompt numbers: [experiments/results/2026-11-22_allmusiccaps_genre_ap.json](experiments/results/2026-11-22_allmusiccaps_genre_ap.json).

| Mean AP | LAION light (app) | MS CLAP 2023 | AMC `all_layers` | AMC `te_trained_sigreg` | chance |
|---|---|---|---|---|---|
| drum and bass (n 257) | 0.41 | 0.70 | 0.90 | **0.92** | 0.35 |
| breakbeat (345) | 0.45 | 0.44 | **0.62** | 0.59 | 0.46 |
| downtempo (99) | **0.19** | 0.11 | 0.18 | 0.14 | 0.13 |
| electro (100) | **0.36** | 0.18 | 0.23 | 0.14 | 0.13 |
| house (69) | 0.23 | 0.13 | **0.34** | 0.22 | 0.09 |
| jungle (19) | 0.19 | 0.14 | **0.37** | 0.21 | 0.03 |
| liquid (26) | 0.04 | 0.07 | 0.16 | **0.20** | 0.03 |
| neurofunk (12) | 0.02 | 0.03 | 0.06 | **0.11** | 0.02 |
| psy (33) | 0.05 | 0.03 | **0.11** | 0.05 | 0.04 |
| **all 27 prompts** | 0.214 | 0.203 | **0.328** | 0.285 | 0.143 |
| 95% interval (bootstrap over tracks, 500) | 0.201-0.237 | 0.189-0.222 | 0.306-0.366 | 0.267-0.320 | |

- **`all_layers` is the best on this library**: +0.11 AP over LAION (interval +0.09 to +0.15), better on 22 of the
  27 prompts. `te_trained_sigreg` is second (+0.07 over LAION, 18 of 27), and below `all_layers` by +0.02 to +0.06:
  MTG's "best overall" is not the best here.
- **Drum and bass is solved** by both MTG models (AP ~0.9, top 10 all DnB for most prompts) where LAION is near
  chance (0.41 vs 0.35). This is the user's biggest genre.
- **Prompt style:** `all_layers` likes bare tags (0.355) and LAION's template (0.340) more than review-style
  captions (0.288); `te_trained_sigreg` is best with captions (0.308). LAION and MS hardly care (0.20-0.22).
- **Where LAION still wins:** electro and downtempo. The `electro` tag is ambiguous in this library (electro breaks
  vs electro), downtempo is close (0.19 vs 0.18).
- **Sub-genres stay hard:** liquid and neurofunk are 2-4x chance for the MTG models but AP is still at most 0.2.
- **Limits:** the interval covers the choice of tracks, not of prompts (27 hand-written prompts are another source
  of variance); tags are sparse and inconsistent (an untagged downtempo track counts as a miss). One library, one DJ.

### int8 and sampled windows, 2026-11-22

Asked: try int8 (the 2026-11-20 int8 test broke LAION and CNN14 because the front end was quantized, see
[2026-11-20_int8_benchmark.md](experiments/results/2026-11-20_int8_benchmark.md)). Numbers:
[2026-11-22_allmusiccaps_int8_sampling.json](experiments/results/2026-11-22_allmusiccaps_int8_sampling.json).

- **Audio int8 works if the first layer stays float.** `quantize_dynamic` (QInt8, per tensor) on the 72 MatMuls that
  multiply by a weight, keeping `embedding_layer/MatMul` (the layer that reads raw waveform patches) and the
  convolutions in float: 296 -> 107 MB, cosine to fp32 0.998 mean / 0.990 worst on the 24 reference windows.
  Quantizing the first layer too drops the worst window to 0.945 (0.89 on DirectML): the same lesson as 2026-11-20.
- **Text int8 does not work:** the FFN down-projections (input right after GELU, outlier activations) break it
  (cosine 0.65 with only those quantized). Attention-only int8 keeps 0.995 but only saves 437 -> 353 MB. Not worth
  it; fp16 for the text file is the better idea for size (not tried).
- **Speed:** int8 is slower on DirectML (39 vs 23 ms per window) and only ~1.3x faster on the CPU in a quiet run
  (105 vs 135 ms), with no gain while the decoder threads ran (145 ms). Not worth shipping for speed.
- **Retrieval (990 tracks, 27 prompts, genre tags):**

  | | Mean AP | 95% interval |
  |---|---|---|
  | AMC fp32, all windows | 0.327 | 0.306-0.366 |
  | AMC fp32, **6 evenly spaced windows** | 0.321 | 0.299-0.357 |
  | AMC int8, 6 windows | 0.322 | 0.300-0.358 |
  | LAION, all windows (the app today) | 0.214 | 0.201-0.237 |

  int8 vs fp32 (6 windows): +0.001 (-0.002 to +0.003), top 10 per prompt overlaps 9.4 of 10 on average. 6 windows vs
  all: -0.006 (-0.016 to +0.002). Over 5,940 windows int8 keeps cosine 0.998 mean, 0.993 at the 1st percentile; one
  window fell to 0.16 (not investigated; likely near-silence).
- **For CPU-only machines this is the useful result:** 6 windows per track search as well as every window, so a
  CPU needs ~6 x 110-170 ms = about 1 s of model time per track (plus decoding) instead of ~5-6 s. int8 adds
  nothing on top. Decision for the app: sample windows on the CPU, keep fp32 files.

### ONNX export probe

Scratch script, not committed: `torch.onnx.export` (TorchScript exporter, opset 17), dynamic batch, then onnxruntime
1.28 on the CPU against PyTorch.

| Tower | Export | Size | ORT vs PyTorch | CPU speed (4 threads) |
|---|---|---|---|---|
| Audio: 10 s waveform at 24 kHz -> 512 (waveform patches, Conformer, layer mean, time mean, projection) | first try, 9 s | 296 MB | max abs diff 5e-6, cosine 1.000000 at batch 2 and 5 | 217 ms per window (PyTorch 247 ms) |
| Text: token ids + mask -> 512 (MPNet, mean pooling, normalise, projection MLP) | first try | 437 MB | max abs diff 1e-5, cosine 1.000000 | 20 ms per query |

The tokenizer is `MPNetTokenizerFast`, so a `tokenizer.json` for the `tokenizers` library the app already uses
(`core/text_search.py`). Fixed 10 s input is fine: the app embeds fixed windows anyway. To check before shipping:
int8 size and accuracy, CPU time per track (~217 ms x 36 windows = ~8 s for a 6-minute track if every window is
embedded: sample windows on CPU).

### DirectML, 2026-11-22

[experiments/clap/amclap_onnx.py](experiments/clap/amclap_onnx.py) (`export` in the research venv, `check` in the
app's `.venv`): `all_layers` exported, then run with the app's runtime (onnxruntime-directml 1.24.4) and the app's
session settings (`DML_OPTIONS`, no memory pattern, sequential). GTX 1650 Ti (4 GB) / i5-10300H. References: 24 real
10 s windows from 6 test-set tracks and 8 prompts, embedded by PyTorch on the CPU.

- **It runs, and matches PyTorch:** audio max abs diff 1e-6, cosine 1.000000; text cosine 1.000000; the best of the
  24 windows is the same for all 8 prompts. CPU provider the same.
- **No spectrogram, so no STFT worry:** the graph has no STFT/DFT node (the model reads waveform patches). Every
  node runs on DirectML except the rotary-position table in each of the 12 attention layers (`Range` -> `Einsum` ->
  `Sqrt`, tiny), which runs on the CPU with 3 small copies per layer. With a fixed 10 s input it is a constant and
  could be folded in later.
- **Speed** (ms per window, median of 20 runs, each batch size in a fresh process):

  | | batch 1 | 2 | 4 | 8 | 16 | CPU, 4 threads |
  |---|---|---|---|---|---|---|
  | AMC `all_layers` | 45.7 | 30.6 | **23.8** | 20.6 | 19.5 | 112-142 |
  | LAION light (app, table above in [text_search_clap.md](text_search_clap.md)) | 69 | **62** | | 244 | | 104-106 |

  About 2.6x faster than LAION on this GPU at the app's batch 4 (LAION is the slower one: 48 kHz input and its own
  spectrogram + Swin). A 6-minute track (36 windows): ~0.9 s on DirectML vs LAION ~2.2 s.
- **Memory:** CNN14 (batch 8) + AMC audio (batch 4 or 8) + AMC text in one process, 25 interleaved rounds: no error
  (223 / 348 ms per round). One run that loaded LAION after AMC batch 16 in the same process hung the GPU
  (DXGI 887A0006); LAION at batch 8+ is already known not to fit this card.
- On the CPU it is slower than LAION per window (112-142 vs ~105 ms), so CPU-only machines need sampled windows.

## The paper, read 2026-11-25

[arXiv:2608.25244](https://arxiv.org/abs/2608.25244) (ISMIR 2026, submitted 2026-08-26). Read from the HTML version
up to Section 8; the tail (the values behind Figure 3, the final variants against external baselines) was not read.

- **Model:** OMAR-RQ small (78 M parameters, conformer, self-supervised on 330 k hours of music) +
  all-MPNet-base-v2 (110 M); 10 s segments at 24 kHz, averaged over time, linear heads to a shared 512-d space
  (§4.1). The paper calls `all_layers` "a learned weighted sum of all OMAR-RQ layers" (§5.2); the released code
  takes a plain mean of the 12 layers (see *Why it could be better*, correction of 2026-11-22). The input
  representation is not discussed in the paper; the code reads raw waveform patches (*Side by side*).
- **Data:** 94,041 AllMusic reviews matched to Discogs, 245,346 tracks, captioned two ways by LLMs (AMCQuotes:
  quotes rewritten; AMCStruct: a fixed schema of style, mood, energy, tempo, instrumentation, production), mixed with
  LP-MusicCaps, M4-RAG and general sound (Freesound, Pro Sound Effects): 80% music, 20% sound (§3, §4.3).
  Pre-training on 6.5 M tracks with raw YouTube/Discogs metadata; caption training ~36 h per model on 8 H100s.
- **Layers** (Table 3, frozen text encoder, InfoNCE): all layers vs the last one: MusicCaps MRR 7.8 vs 7.3, Song
  Describer MRR 19.3 vs 18.8, DimSim (audio similarity) 83.0 vs 74.3; probing about the same. The +8.7 points on
  similarity fit `all_layers` winning on this library's genre tags.
- **Objectives:** a trainable text encoder helps text-to-music retrieval but hurts audio similarity (DimSim);
  InfoNCE+SigReg and LeJEPA beat InfoNCE on classification; models peak early (20-60 k steps) (§5.3).
- **Descriptive queries:** review supervision helps text-to-music retrieval most for the most complex captions
  (Song Describer, complexity scores 3-4, Figure 2): the model is meant for long descriptions, not only tags.
- **Weak spot:** instruments. No variant beats the strongest external baseline on MTG-Jamendo Instrument; reviews
  describe genre, scene and mood better than instrumentation (§5.4). Beats LAION-CLAP, TTMR++ and CLaMP3 on most
  other tasks.
- **Not in the paper:** any mel-spectrogram encoder as a comparison, inference cost, compression or distillation.
  The distilled students (experiments/distill/) are new ground, not a reproduction.
- **Licence statement:** "All materials derived from this work, including the AllMusicCaps dataset, model weights,
  and code, are released for non-commercial scientific research purposes only" (§1). That is narrower wording than
  the CC BY-NC-SA 4.0 on the weights' model card. To settle before shipping anything trained from these weights
  (a distilled student included), and worth a look for the app's AllMusicCaps entry too.

## Sources

- [mtg-upf/allmusiccaps_all_layers](https://huggingface.co/mtg-upf/allmusiccaps_all_layers) (model card)
- [MTG/allmusiccaps](https://github.com/MTG/allmusiccaps) (code, variant table, dependencies)
- [mtg-upf/allmusiccaps](https://huggingface.co/datasets/mtg-upf/allmusiccaps) (dataset card, gated)
- [mtg-upf/allmusiccaps_sigmoid](https://huggingface.co/mtg-upf/allmusiccaps_sigmoid) (variant card)
- [OMAR-RQ, arXiv:2507.03482](https://arxiv.org/abs/2507.03482)
- [What Makes a Good Layer?, arXiv:2608.14819](https://arxiv.org/pdf/2608.14819) (layer-wise analysis of music models)
- Paper: Alonso-Jiménez, Lizarraga-Seijas, Serra, Bogdanov, "AllMusicCaps: Album Reviews as Complementary
  Supervision for Music CLAP", ISMIR 2026, [arXiv:2608.25244](https://arxiv.org/abs/2608.25244) (not online yet on
  2026-11-21; read 2026-11-25, see *The paper*).

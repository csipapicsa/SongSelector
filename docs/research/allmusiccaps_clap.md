# AllMusicCaps CLAP (MTG) vs LAION CLAP

Desk research, 2026-11-21: nothing here has been run on the library yet. Sources: the model and dataset cards on
Hugging Face, the GitHub repo `MTG/allmusiccaps`, the OMAR-RQ paper (links at the end). The model card has **no
benchmark numbers**, and the paper (ISMIR 2026) was not found online, so every quality claim below is a hypothesis to
measure.

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
| Audio encoder | HTSAT-tiny, 28 M parameters, trained on general audio | OMAR-RQ: self-supervised (masked token prediction, BEST-RQ style) on 330 k hours of music, then CLAP training on top |
| Text encoder | RoBERTa, trained with the audio side | `all-mpnet-base-v2` (sentence-transformers), **frozen** |
| Captions | Mostly sound descriptions; AudioSet tags turned into sentences | ~540 k (YouTube track, Discogs release) pairs with captions written by an LLM from AllMusic album reviews: style, mood, tempo, energy, instrumentation, production |
| Input | 48 kHz, 10 s windows | 24 kHz mono; window length not stated (the README example uses 10 s) |
| Embedding | 512, cosine | 512, cosine |
| Runtime | ONNX, in the app | PyTorch only: `amclap` package (lightning, gin-config, sentence-transformers <5.2, omar-rq ~0.2, torch >= 2.6). No ONNX export exists |
| File | 122 MB audio + 501 MB text (ONNX) | `model.ckpt` 296 MB; text encoder weights downloaded separately at construction |
| License | Apache 2.0 | Weights CC BY-NC-SA 4.0, code AGPL-3.0, dataset CC BY-NC-SA 4.0 (non-commercial research) |
| Published results | Yes (LAION paper) | None on the card or in the repo |

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
- **All layers, weighted.** Middle layers of music models tend to hold timbre and rhythm, which matter for genre;
  `all_layers` learns how much of each layer to use instead of only the last one.

## Caveats

1. **Test `te_trained_sigreg` too**, not only `all_layers` (the variant first looked at).
2. **Noisy labels.** One album review captions every track of the album, and an LLM wrote the captions. Drum and
   bass did not appear in the part of the 50-row sample we could read: its coverage is unknown.
3. **Frozen text encoder.** A general sentence model may not separate "reese" from "wobble"; probably why the
   trained-text-encoder variant wins.
4. **Integration cost.** A new ONNX export (Conformer encoder plus OMAR-RQ's front end), expect tracing problems like
   msclap's frozen batch size. Speed *to measure*: the 296 MB checkpoint suggests ~75 M audio parameters, close to
   LAION's music model (69 M), which ran ~2x slower than LAION light in eager PyTorch.
5. **License.** Non-commercial terms are workable for a free GPL tool that downloads models separately (as concluded
   for the other MTG models in [model_candidates.md](model_candidates.md)). Share-alike: our ONNX conversion on
   Hugging Face would be published under CC BY-NC-SA 4.0 with credit to MTG.

## Plan to settle it

Step 1 of [text_search_clap.md](text_search_clap.md) (precision of the top 10 per label) was never run, so there is
no number for LAION either. In order:

1. Add `amclap` (`all_layers`, `te_trained_sigreg`) to
   [experiments/clap/extract_embeddings.py](experiments/clap/extract_embeddings.py), same 998-track set (Traktor
   rating 4-5 with a colour), in the WSL research venv (torch >= 2.6).
2. ~3 prompts per folder genre (DnB, breakbeat, ...), precision of the top 10 for LAION light, MS CLAP 2023 and the
   two MTG variants. Also the similarity-map question from the backlog: neighbour purity with the user's labels,
   CNN14 vs the MTG audio embedding.
3. Only if it wins: ONNX export checked against PyTorch, speed on DirectML and CPU, then a model entry in the app.

## Sources

- [mtg-upf/allmusiccaps_all_layers](https://huggingface.co/mtg-upf/allmusiccaps_all_layers) (model card)
- [MTG/allmusiccaps](https://github.com/MTG/allmusiccaps) (code, variant table, dependencies)
- [mtg-upf/allmusiccaps](https://huggingface.co/datasets/mtg-upf/allmusiccaps) (dataset card, gated)
- [mtg-upf/allmusiccaps_sigmoid](https://huggingface.co/mtg-upf/allmusiccaps_sigmoid) (variant card)
- [OMAR-RQ, arXiv:2507.03482](https://arxiv.org/abs/2507.03482)
- [What Makes a Good Layer?, arXiv:2608.14819](https://arxiv.org/pdf/2608.14819) (layer-wise analysis of music models)
- Paper: Alonso-Jiménez, Lizarraga-Seijas, Serra, Bogdanov, "AllMusicCaps: Album Reviews as Complementary
  Supervision for Music CLAP", ISMIR 2026 (not found online on 2026-11-21).

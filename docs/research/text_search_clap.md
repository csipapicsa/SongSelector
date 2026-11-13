# Free-text track search with CLAP: CPU cost (2026-11-13)

**Idea** (backlog, 2026-11-13): type a description ("dark rolling DnB with a reese bass") and get the closest tracks
in a window; prompts can be saved. A CLAP model (contrastive language-audio pretraining) has an audio encoder and a
text encoder that map into the same vector space: every track gets an audio vector once, in the background, and each
query becomes a text vector that is ranked against them by cosine similarity.

**Question of this note:** before any app work, is it affordable **on the CPU alone** (users without CUDA)? How long
does analysing a library take, how fast is a query, how much memory? Whether it finds the *right* tracks is the next
question (not answered here).

## Setup

| | |
|---|---|
| Machine | Intel Core i5-10300H (4 cores, 8 threads), 32 GB RAM, laptop; nothing else heavy running |
| Software | PyTorch 2.7.1 (CPU build), transformers 4.57.6, msclap 1.3.4, Python 3.12, isolated venv in `.research_cache/` |
| Device | CPU only (CUDA hidden). ONNX Runtime, which the app uses, is *not* measured yet |
| Tracks | 8 random tracks from the developer's library (seed 1), 3.8–7.9 min, 45.6 min of audio in total |
| Decoding | soundfile + soxr HQ to the model's rate, the app's decoding stack |
| Method | Each model and thread count in its own process. Window times: median of repeats after warm-up, random audio. Track times: every window of every track, batches of 8. One run per configuration |
| Code / data | [experiments/clap/benchmark_cpu.py](experiments/clap/benchmark_cpu.py), [results/2026-11-13_clap_cpu.json](experiments/results/2026-11-13_clap_cpu.json) |

Models: the light version of each family, plus LAION's music-trained model as a reference.

| Model | Audio encoder | Text encoder | Download | Window | Vector | Licence |
|---|---|---|---|---|---|---|
| LAION `clap-htsat-unfused` | HTSAT-tiny, 28 M parameters | RoBERTa, 125 M | 615 MB | 10 s at 48 kHz | 512 | Apache 2.0 |
| Microsoft CLAP 2023 | HTSAT, 33 M | GPT-2, 126 M | 690 MB | 7 s at 44.1 kHz | 1024 | MS-PL |
| LAION `larger_clap_music` (reference) | HTSAT-base, 69 M | RoBERTa, 125 M | 776 MB | 10 s at 48 kHz | 512 | Apache 2.0 |

Microsoft CLAP 2022 (2.3 GB) was left out as the heavier Microsoft version.

**Yardstick**, set from what the app already accepts: CNN14 on the CPU takes about 6.4 s per 6-minute track (about
5.3 h for a first pass over 3,000 tracks); a query should answer in under about 200 ms to feel instant. (Set after a
one-track smoke test, not before any numbers were seen.)

## Results (4 threads, as the app's analysis process uses; 8 threads in brackets)

| | LAION light | MS CLAP 2023 | LAION music |
|---|---|---|---|
| One window, batch 8 (incl. LAION's mel features, 19 ms) | 124 ms (113) | 126 ms (124) | 285 ms (267) |
| Decoding, per minute of audio | 0.13 s | 0.12 s | 0.14 s |
| **Whole 6-minute track, every window** | **5.5 s** (5.2) | 7.2 s (7.0) | 11.3 s (9.9) |
| → 3,000 tracks, first pass | 4.6 h (4.3) | 6.0 h (5.9) | 9.4 h (8.3) |
| 6-minute track, 6 sampled windows *(derived)* | 1.5 s | 1.5 s | 2.6 s |
| → 3,000 tracks, first pass *(derived)* | 1.3 h | 1.2 h | 2.1 h |
| **Text query** (median of 10 prompts) | **31 ms** | 121 ms (149) | 35 ms |
| Ranking 3,000 tracks (top 10) | 0.2 ms | 0.4 ms | 0.2 ms |
| Model load | 6.3 s | 7.8 s | 6.1 s |
| Memory after load / peak while analysing | 0.6 / 1.6 GB | 1.9 / 2.4 GB | 0.6 / 1.9 GB |

"Sampled" = 6 windows spread over the track instead of all of them (60 s of audio for LAION, 42 s for MS). It is
computed from the measured decode time and batch-8 window time, not measured end to end.

## Reading

- **CPU is acceptable.** LAION light needs 5.5 s per track for every window, slightly *less* than the CNN14 CPU path
  the app already ships (6.4 s). With 6 sampled windows it is about 1.5 s per track, and decoding is half of that:
  the analysis process already decodes each track for CNN14, so decoding once for both would leave about 0.7 s of
  CLAP work per track.
- **Queries are instant on all three.** Encoding the text takes 31–121 ms, and ranking is negligible, so a search
  window can answer as you type (with a short debounce).
- **8 threads barely help** (4–12 %): the CPU has 4 physical cores, and hyper-threads add little to this workload.
  The app's choice of half the logical cores for the analysis process holds, and leaves room for Traktor.
- **LAION light is the lighter model on every measure:** 25 % less time per track (fewer, longer windows), 4× faster
  queries (RoBERTa on the real token count vs GPT-2 padded to 77 tokens), less memory, half the vector size.
  Microsoft's 1.9 GB after loading comes from loading GPT-2 next to its checkpoint.
- **The music-trained LAION model costs about twice as much** (69 M audio parameters vs 28 M) but stays usable with
  sampling (2.1 h for 3,000 tracks). It is the fallback if the general-audio model does not understand music prompts.
- **Memory can be split.** Analysis needs only the audio encoder (28 M parameters, about 110 MB in float32), the search
  window only the text encoder (125 M, about 500 MB). Exported separately to ONNX, neither process would carry the
  other half.

Caveats: one laptop, one run per configuration, PyTorch rather than ONNX Runtime (for CNN14, ONNX Runtime was 1.49x
faster on the CPU than eager PyTorch, see `audio_embeddings.md`, so these numbers are likely on the pessimistic side); the sampled figures are derived.

## Decision and next steps

Candidate: **LAION `clap-htsat-unfused`**. Cost is not the blocker. Next, in order:

1. **Does it find the right tracks?** Prompts for styles the library has labels for (folders: breakbeat, DnB, ...)
   and precision of the top 10, LAION light vs LAION music (MS 2023 too, if it is cheap to include). Also: does
   sampling 6 windows rank as well as all windows?
2. ONNX export of the two encoders separately, check against PyTorch, measure ONNX Runtime on the CPU and DirectML.
3. Only then the app: background analysis next to CNN14 (decode once), a search window with saved prompts.

## Trying it on the library (2026-11-13)

- **Test set:** the 998 tracks with a Traktor rating of 4-5 and a colour whose files exist.
  [experiments/clap/extract_embeddings.py](experiments/clap/extract_embeddings.py) stores every window's vector per model
  in `.research_cache/clap/` (git-ignored). For this offline run it uses the GPU (CUDA). Each track is decoded once for
  all models, with parallel decoding threads. GPU and CPU embeddings agree to 3e-7.
- **Notebook:** [experiments/clap/text_search.ipynb](experiments/clap/text_search.ipynb): write a prompt, see the top 10.
- **First look (75 tracks):** with LAION light, *"dark rolling drum and bass with a heavy reese bassline"* put 8 DnB
  tracks (around 174 BPM) in the top 10. On DnB tracks, *"This audio is a drum and bass song."* scored 0.44–0.47 against
  0.20–0.30 for plain *"drum and bass"*, so the wording of a prompt matters. Microsoft CLAP 2023 also separates
  sensibly ("drum and bass" 0.27, "a dog barking" 0.02).
- **`laion/larger_clap_music` is broken in this setup** (transformers 4.57.6, torch 2.7.1). All weights load, but every
  text and every track get nearly the same vector: mean cosine 0.999 between different texts and 0.98 between
  different tracks, against 0.29 and 0.82 for LAION light. Its scores are meaningless, so it is excluded for now.
  To check later: the original checkpoint `music_audioset_epoch_15_esc_90.14.pt` through the `laion_clap` package.
- **Extraction finished:** 990 of 998 tracks for LAION light and MS 2023; 8 files libsndfile cannot decode (the app
  falls back to FFmpeg for those, this script does not). GTX 1650 Ti, both models together: 2.2 s per track, about
  33 minutes for the set.

## ONNX export and speed in the app (2026-11-13)

`scripts/export_clap_onnx.py` exports both models (audio and text encoder each) and checks them against PyTorch
before writing them. Unit-length vectors, largest difference / lowest cosine:

| Check | LAION light | Microsoft 2023 |
|---|---|---|
| Spectrogram built into the graph vs transformers' feature extractor | 7.8e-08 / 1.000000 | (spectrogram is part of the model already) |
| ONNX audio vs PyTorch (batch of 3) | 6.4e-07 / 1.000000 | 3.0e-07 / 1.000000 |
| ONNX text via the app's tokenizer path vs PyTorch (3 prompts) | 4.7e-07 / 1.000000 | 1.2e-07 / 1.000000 |
| App pipeline (soundfile + soxr + ONNX, DirectML and CPU) vs the research embeddings, one real track | cosine 1.000000 | cosine 1.000000 |

Two problems the checks caught:
- **msclap's HTSAT froze the batch size.** `window_reverse` computes it with `int(windows.shape[0] / ...)`, which
  tracing turns into a constant: batch 1 was exact, batch 3 gave cosine 0.62. The export replaces it with the same
  arithmetic using `view(-1, ...)`; LAION's HTSAT (transformers) did not have this problem.
- **transformers 4.57 builds attention masks with `torch.vmap`** on PyTorch >= 2.6, which the ONNX tracer cannot
  follow ("invalid unordered_map key"). Its implementation for older PyTorch builds the same mask without vmap; the
  export switches to it. GPT-2's key/value cache was also switched off (`use_cache=False`).

Files: LAION 122 MB audio + 501 MB text + 4 MB tokenizer; Microsoft 127 + 505 + 4 MB.

Audio encoder speed with ONNX Runtime 1.24 (the app's runtime), GTX 1650 Ti / i5-10300H, ms per window:

| | DirectML batch 1 | batch 4 | batch 8 | CPU (4 threads) |
|---|---|---|---|---|
| LAION (10 s windows) | 69 | **62** | 244 | 104-106 |
| Microsoft (7 s windows) | 56 | **55** | 152 | 107-118 |

Batch 8 runs out of room on the 4 GB card, so the app uses 4 on DirectML (CNN14 stays at 8). A 6-minute track on
DirectML: LAION ~2.2 s, Microsoft ~2.8 s, CNN14 0.6 s, plus one 0.8 s decode for all of them. A first observation
that DirectML was slower than the CPU came from a different-sized last batch: DirectML re-plans the model for every
new input shape, which the app avoids by padding batches.

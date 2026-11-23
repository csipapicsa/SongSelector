---
license: cc-by-nc-sa-4.0
library_name: onnx
pipeline_tag: feature-extraction
base_model: mtg-upf/allmusiccaps_all_layers
tags:
- onnx
- audio
- music
- clap
- text-to-audio-retrieval
- songselector
---

# AllMusicCaps CLAP `all_layers` by MTG (ONNX) for SongSelector

> **This is not my model.** AllMusicCaps CLAP was made by the
> [Music Technology Group (MTG), Universitat Pompeu Fabra](https://www.upf.edu/web/mtg). The original is
> [mtg-upf/allmusiccaps_all_layers](https://huggingface.co/mtg-upf/allmusiccaps_all_layers). This repo only holds an
> ONNX conversion of it, so that [SongSelector](https://github.com/csipapicsa/SongSelector) can run it without
> PyTorch. Credit for the model, its training data and its quality goes to MTG. **Non-commercial use only**
> (CC BY-NC-SA 4.0, see below).

A CLAP model trained on music: the audio encoder gives each 10 s of a track a vector, the text encoder turns a typed
description ("dark rolling drum and bass") into a vector in the same space, and the closest tracks win. SongSelector
downloads these files itself (*Analysis → Get models…*) and checks each against the SHA-256 below; there is nothing to
download by hand.

## Files

| File | Size (bytes) | SHA-256 |
|---|---|---|
| `clap-amc-audio.onnx` | 295,550,979 | `1fb193cbddef664e95303fef3b4cbf0b3c7519b42c61b4bd16f3e86be5c6b378` |
| `clap-amc-text.onnx` | 437,419,780 | `b75c45c5d7581ac9899b01c1def30019782ba777f9aa6ee2da78dbd5a1de2068` |
| `clap-amc-tokenizer.json` | 710,932 | `46fb1f735006f52c1f9744bb05f7bc1544ec8475955af30396212c7737558d1e` |
| `LICENSE` | | Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International |

## Inputs and outputs

| File | Inputs | Output |
|---|---|---|
| `clap-amc-audio.onnx` | `audio`: float32 `(batch, 240000)`, 10 s of mono audio at 24 kHz | `embedding`: float32 `(batch, 512)` |
| `clap-amc-text.onnx` | `input_ids`, `attention_mask`: int64 `(batch, tokens)` | `embedding`: float32 `(batch, 512)` |

Token ids come from `clap-amc-tokenizer.json` (the MPNet tokenizer of `sentence-transformers/all-mpnet-base-v2`, for
the [`tokenizers`](https://github.com/huggingface/tokenizers) library), at the text's own length. Compare audio and
text embeddings with cosine similarity. ONNX opset 17, runs with onnxruntime (CPU and DirectML tested).

## How it was made

Exported from `amclap` 0.1.0 (MTG's package) with
[`amclap_onnx.py`](https://github.com/csipapicsa/SongSelector/blob/main/docs/research/experiments/clap/amclap_onnx.py):
the audio tower is MTG's `forward_audio` (OMAR-RQ encoder, mean of all layers, projection), the text tower is the
sentence-transformers MPNet encoder with MTG's text projection. Both were checked against the PyTorch model on real
music: cosine similarity 1.000000, largest absolute difference about 1e-5. Weights are unchanged; only the format is.

How it compares with other CLAP models on one DJ's genre tags (a small, personal test, not a benchmark):
[allmusiccaps_clap.md](https://github.com/csipapicsa/SongSelector/blob/main/docs/research/allmusiccaps_clap.md).

## Source, credit and licence

- **Model:** [mtg-upf/allmusiccaps_all_layers](https://huggingface.co/mtg-upf/allmusiccaps_all_layers), by MTG,
  Universitat Pompeu Fabra. Code: [MTG/allmusiccaps](https://github.com/MTG/allmusiccaps) (AGPL-3.0).
- **Audio encoder:** OMAR-RQ, [arXiv:2507.03482](https://arxiv.org/abs/2507.03482).
- **Text encoder:** [sentence-transformers/all-mpnet-base-v2](https://huggingface.co/sentence-transformers/all-mpnet-base-v2)
  (Apache 2.0), as used by MTG.

The original weights are licensed under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/), and so is this conversion (ShareAlike):
**attribution to MTG, non-commercial use only, share adaptations under the same licence.** Changes: converted to
ONNX; nothing retrained or fine-tuned. No warranty. This repo is not affiliated with or endorsed by MTG.

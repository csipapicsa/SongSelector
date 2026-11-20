---
license: apache-2.0
library_name: onnx
pipeline_tag: feature-extraction
base_model: laion/clap-htsat-unfused
tags:
- onnx
- audio
- music
- clap
- text-to-audio-retrieval
- songselector
---

# LAION CLAP `clap-htsat-unfused` (ONNX) for SongSelector

[LAION CLAP](https://huggingface.co/laion/clap-htsat-unfused) converted to ONNX, as used by
[SongSelector](https://github.com/csipapicsa/SongSelector): the audio encoder gives each track a vector, the text
encoder turns a typed description ("dark rolling techno") into a vector in the same space, and the closest tracks
win. The app downloads these files itself (*Analysis → Download models…*) and checks each against the SHA-256 below;
there is nothing to download by hand.

## Files

| File | Size (bytes) | SHA-256 |
|---|---|---|
| `clap-laion-audio.onnx` | 121,612,865 | `3c736ebc3a05f8cc652b93f2306e4c12eb714aba9e455f2c17541ed63042d55c` |
| `clap-laion-text.onnx` | 501,449,463 | `2cebcbe969166aa29db1750c688103cefc474b9ae478d747a3b4faa346ec5bbd` |
| `clap-laion-tokenizer.json` | 3,558,802 | `4fd1d86b4f5b53f40a609fcd11c1f34024b735f870a07439d70202b98493661a` |
| `LICENSE` | | Apache License 2.0 |

## Inputs and outputs

| File | Inputs | Output |
|---|---|---|
| `clap-laion-audio.onnx` | `audio`: float32 `(batch, 480000)`, 10 s of mono audio at 48 kHz | `embedding`: float32 `(batch, 512)` |
| `clap-laion-text.onnx` | `input_ids`, `attention_mask`: int64 `(batch, tokens)` | `embedding`: float32 `(batch, 512)` |

The log-mel spectrogram, which transformers' feature extractor computes in Python for the original model, is part
of the audio graph, so the model takes raw audio. Token ids come from `clap-laion-tokenizer.json` (RoBERTa tokenizer,
for the [`tokenizers`](https://github.com/huggingface/tokenizers) library). Compare audio and text embeddings with
cosine similarity. ONNX opset 17, runs with onnxruntime.

## How it was made

Exported with
[`scripts/export_clap_onnx.py --models laion`](https://github.com/csipapicsa/SongSelector/blob/main/scripts/export_clap_onnx.py);
the script checks both encoders against the original PyTorch model (and the audio side against transformers'
feature extractor) before it writes the files.

## Source and licence

Wu, Chen, Zhang, Hui, Berg-Kirkpatrick, Dubnov: "Large-scale Contrastive Language-Audio Pretraining with Feature
Fusion and Keyword-to-Caption Augmentation", ICASSP 2023. Weights:
[laion/clap-htsat-unfused](https://huggingface.co/laion/clap-htsat-unfused), Apache License 2.0 (see `LICENSE`).

Changes: converted to ONNX, with the log-mel spectrogram added to the audio graph. Shared under the Apache License
2.0. No warranty.

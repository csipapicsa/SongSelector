---
license: cc-by-4.0
library_name: onnx
pipeline_tag: feature-extraction
tags:
- onnx
- audio
- music
- audio-embeddings
- panns
- songselector
---

# PANNs CNN14 (ONNX) for SongSelector

[PANNs CNN14](https://zenodo.org/records/3987831) converted to ONNX, as used by
[SongSelector](https://github.com/csipapicsa/SongSelector) for audio similarity between tracks. The app downloads
this file itself (*Analysis → Download models…*) and checks it against the SHA-256 below; there is nothing to
download by hand.

## Files

| File | Size (bytes) | SHA-256 |
|---|---|---|
| `cnn14.onnx` | 327,330,336 | `ae868eda6e9734f4722d61fe70e45ce215c316e3fe306023105ff3c0a9e73a32` |

## Inputs and outputs

| Name | Type and shape | Meaning |
|---|---|---|
| `audio` (input) | float32 `(batch, 160000)` | 5 s of mono audio at 32 kHz, samples in [-1, 1] |
| `embedding` | float32 `(batch, 2048)` | the embedding SongSelector uses; compare with cosine similarity |
| `clipwise_output` | float32 `(batch, 527)` | AudioSet tag probabilities (not used by the app) |

ONNX opset 17, runs with onnxruntime.

## How it was made

The published checkpoint `Cnn14_mAP=0.431.pth` (SHA-256
`0dc499e40e9761ef5ea061ffc77697697f277f6a960894903df3ada000e34b31`) exported with
[`scripts/export_cnn14_onnx.py`](https://github.com/csipapicsa/SongSelector/blob/main/scripts/export_cnn14_onnx.py);
the script checks that onnxruntime gives the same embeddings as PyTorch before it writes the file.

## Source and licence

Kong, Cao, Iqbal, Wang, Wang, Plumbley: "PANNs: Large-Scale Pretrained Audio Neural Networks for Audio Pattern
Recognition", IEEE/ACM Transactions on Audio, Speech, and Language Processing, 2020. Weights:
[zenodo.org/records/3987831](https://zenodo.org/records/3987831), licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Changes: converted to ONNX (graph format changed, weights unchanged). This file is shared under the same licence,
CC BY 4.0. No warranty.

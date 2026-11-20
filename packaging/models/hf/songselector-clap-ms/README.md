---
license: ms-pl
library_name: onnx
pipeline_tag: feature-extraction
base_model: microsoft/msclap
tags:
- onnx
- audio
- music
- clap
- text-to-audio-retrieval
- songselector
---

# Microsoft CLAP 2023 (ONNX) for SongSelector

[Microsoft CLAP 2023](https://huggingface.co/microsoft/msclap) converted to ONNX, as used by
[SongSelector](https://github.com/csipapicsa/SongSelector): the audio encoder gives each track a vector, the text
encoder turns a typed description ("dark rolling techno") into a vector in the same space, and the closest tracks
win. The app downloads these files itself (*Analysis → Download models…*) and checks each against the SHA-256 below;
there is nothing to download by hand.

## Files

| File | Size (bytes) | SHA-256 |
|---|---|---|
| `clap-ms-audio.onnx` | 126,555,913 | `e9b5c1cc2e43cd870a3df94535774bd4aed5456f0a7cc8c519a82e80c84b7ff2` |
| `clap-ms-text.onnx` | 505,456,227 | `0a26534f6e03c32312836c0f9b83aa358ddac0852a7bfd1e50136ea4bc6b6715` |
| `clap-ms-tokenizer.json` | 3,557,853 | `0fa4827ec39265089e822a6491293827737093c837ad8fa3ad9f20f2d76308cf` |
| `LICENSE` | | Microsoft Public License (Ms-PL) |

## Inputs and outputs

| File | Inputs | Output |
|---|---|---|
| `clap-ms-audio.onnx` | `audio`: float32 `(batch, 308700)`, 7 s of mono audio at 44.1 kHz | `embedding`: float32 `(batch, 1024)` |
| `clap-ms-text.onnx` | `input_ids`, `attention_mask`: int64 `(batch, 77)` | `embedding`: float32 `(batch, 1024)` |

Token ids come from `clap-ms-tokenizer.json` (GPT-2 tokenizer, for the
[`tokenizers`](https://github.com/huggingface/tokenizers) library): as msclap does, `' <|endoftext|>'` is appended to
the text, and the ids are cut at 77 or padded with id 0 to 77 (`attention_mask` 0 on the padding). Compare audio and
text embeddings with cosine similarity. ONNX opset 17, runs with onnxruntime.

## How it was made

Exported with
[`scripts/export_clap_onnx.py --models ms`](https://github.com/csipapicsa/SongSelector/blob/main/scripts/export_clap_onnx.py)
(msclap 1.3.4); the script checks both encoders against the original PyTorch model before it writes the files.

## Source and licence

Elizalde, Deshmukh, Wang: "Natural Language Supervision for General-Purpose Audio Representations",
[arXiv:2309.05767](https://arxiv.org/abs/2309.05767), 2023. Weights:
[microsoft/msclap](https://huggingface.co/microsoft/msclap), Microsoft Public License (see `LICENSE`).

Changes: converted to ONNX. Shared under the Microsoft Public License. No warranty.

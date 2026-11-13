# SongSelector model files (v1)

Embedding models for SongSelector, converted to ONNX so the app runs them with onnxruntime (no PyTorch). The app
downloads them itself (*Analysis → Download models…*) and checks each file against `SHA256SUMS.txt`.
They can also be rebuilt from the original weights with `scripts/export_cnn14_onnx.py` and
`scripts/export_clap_onnx.py` in the SongSelector repository; every export is checked against the original
PyTorch model (largest difference 1e-5 or less).

| Files | Model | Original weights | Licence of the weights |
|---|---|---|---|
| `cnn14.onnx` | PANNs CNN14 (audio, 2048 values per 5 s) | Kong, Cao, Iqbal, Wang, Wang, Plumbley: "PANNs: Large-Scale Pretrained Audio Neural Networks for Audio Pattern Recognition", 2020. [zenodo.org/records/3987831](https://zenodo.org/records/3987831) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Converted to ONNX (graph format changed; weights unchanged) |
| `clap-laion-audio.onnx`, `clap-laion-text.onnx`, `clap-laion-tokenizer.json` | LAION CLAP `clap-htsat-unfused` (audio and text, 512 values per 10 s) | Wu, Chen, Zhang, Hui, Berg-Kirkpatrick, Dubnov: "Large-scale Contrastive Language-Audio Pretraining with Feature Fusion and Keyword-to-Caption Augmentation", 2023. [huggingface.co/laion/clap-htsat-unfused](https://huggingface.co/laion/clap-htsat-unfused) | Apache License 2.0, see `LICENSE-Apache-2.0.txt`. Changed: converted to ONNX, with the log-mel spectrogram (previously computed by transformers' feature extractor) added to the audio graph |
| `clap-ms-audio.onnx`, `clap-ms-text.onnx`, `clap-ms-tokenizer.json` | Microsoft CLAP 2023 (audio and text, 1024 values per 7 s), text side based on GPT-2 | Elizalde, Deshmukh, Wang: "Natural Language Supervision for General-Purpose Audio Representations", 2023. [huggingface.co/microsoft/msclap](https://huggingface.co/microsoft/msclap) | Microsoft Public License (Ms-PL), see `LICENSE-MS-PL.txt`. Converted to ONNX |

The tokenizer files come from the models' own tokenizers (RoBERTa for LAION, GPT-2 for Microsoft; both MIT).
No warranty: see the licences.

# Audio embeddings: reference from the DJ mix segmentation project

Status: implemented in 4.7.0 (`core/embeddings.py`, design in `docs/ARCHITECTURE.md`).
This note keeps the background and the measurements behind the design. Next use:
track similarity.

Source project: `E:\GITHUB_E\MusicFindBoundaries` (not part of this repo).

## The embedding model: PANNs CNN14

| Item | Value |
|---|---|
| Model | **CNN14** from PANNs (Kong et al., 2020, "PANNs: Large-Scale Pretrained Audio Neural Networks"), trained on AudioSet |
| Python package | `panns-inference==0.1.1` |
| Checkpoint | `Cnn14_mAP=0.431.pth` (327 MB), auto-downloaded to `%USERPROFILE%\panns_data\`. Already present on the development machine. |
| ONNX export | `MusicFindBoundaries\cnn14.onnx` (327 MB), input shape `(1, 160000)`; created in `audio to embeddings.ipynb` for `onnxruntime` |
| Input | mono, **32 kHz**, **5-second** chunks (160,000 samples); the last chunk is zero-padded |
| Output | one **2048-dimensional** embedding per chunk (the second return value of `AudioTagging.inference`) |
| Storage | `np.savez_compressed(path, embeddings=array.astype(np.float16))`, shape `(n_chunks, 2048)` |

Extraction code (from `DJ MIX TO EMBEDDINGS.ipynb`):

```python
from panns_inference import AudioTagging
import librosa, numpy as np

SR, CHUNK_SEC = 32000, 5.0
CHUNK_SAMPLES = int(SR * CHUNK_SEC)
at = AudioTagging(checkpoint_path=None, device='cuda')   # or 'cpu'

audio, _ = librosa.load(file_path, sr=SR, mono=True)
embeddings = []
for start in range(0, len(audio), CHUNK_SAMPLES):
    chunk = audio[start:start + CHUNK_SAMPLES]
    if len(chunk) < CHUNK_SAMPLES:
        chunk = np.pad(chunk, (0, CHUNK_SAMPLES - len(chunk)))
    _, emb = at.inference(chunk[None, :])                 # emb: (1, 2048)
    embeddings.append(emb[0])
np.savez_compressed(out_path, embeddings=np.stack(embeddings).astype(np.float16))
```

## What exists in the source project

- `embeddings\*.npz`: 2362 mixes as CNN14 embeddings (no filename prefix), plus
  3731 `melspec_*` and 189 `mfcc_*` files. These two are hand-crafted feature
  variants, not model embeddings.
- Segmentation heads trained on top of the features: `best_model_CNN14.pt`
  (2026-03-03), `best_model_MEL_SPEC*.pt` (2026-03-03/04), `best_model_MFCC.pt`.
- Logged validation peak-F1 for transition detection: about **0.65** with CNN14
  embeddings (`MODEL.ipynb`) and about **0.68** in the later mel/MFCC run
  (`MODEL_2_MFCC_MEL.ipynb`). The runs used different datasets and settings, so the
  numbers are not a like-for-like comparison.

## Measurements behind the implementation (2026-10-27)

All on one real 6-minute track (72 chunks), unless noted.

| Question | Result |
|---|---|
| Same output as the original pipeline? | Decoding with soundfile + soxr is **bit-identical** to `librosa.load`; ONNX embeddings differ from PyTorch `panns_inference` by at most 1.1e-05 (float32 rounding, below float16 precision) |
| Is 2048 the real dimension? | Yes: ONNX output `embedding [batch, 2048]`, stored files `(n, 2048)`, `MODEL.ipynb` trains on `(T, 2048)` |
| How compressible? | 86.8 % of values are exactly 0 (ReLU). float16 + zlib (lossless): 21 % of raw over 100k frames; this track 49 KB instead of 288 KB |
| Alternatives considered | uint8 + zlib: ~13 % of raw, cosine 0.99999 (lossy). PCA 256 dims: 97.7 % variance (lossy, needs a fitted basis). Not used: storing full data keeps every option open, and recomputing takes hours |
| CPU speed (4 of 8 threads) | 5.5 s model + 0.8 s decode per track; batching does not help |
| GPU speed (GTX 1650 Ti, onnxruntime-gpu 1.22, CUDA 12) | 1.6 s one chunk at a time, **0.6 s in batches of 16**, + 0.8 s decode, so ~4x faster per track |
| PyTorch vs compiled vs onnxruntime on the CPU (2026-10-30, 10 random library tracks, 60.8 min of audio, 4 threads, `tests/test_inference_speed.py`) | Model time per track: PyTorch eager 10.5 s, TorchScript 8.0 s (1.32x), onnxruntime without graph optimisations 7.3 s (1.45x), onnxruntime as the app 7.1 s (**1.49x**). Model load 6.9 s vs 1.0 s. Most of the gain comes from not driving each layer from Python; the graph optimisations add only ~2 %. Same embeddings (max diff 2e-05) |
| onnxruntime-gpu 1.31 | Built for CUDA 13, which needs NVIDIA driver ≥ 580 (this machine: 555.97), so it falls back to the CPU |

Library estimate (5,105 tracks, 6-minute average): about 9 h on the CPU or 2 h on the
GPU for the first pass, and about 250 MB in `embeddings.sqlite`.

## Similarity and map layout (2026-10-27, 446–699 analysed tracks: DnB and breakbeat folders)

| Question | Result |
|---|---|
| Raw mean vectors | All very alike: median cosine of random pairs 0.948, of nearest neighbours 0.988 |
| Per-track vector (judged by folder = style) | Breakbeat tracks' 10 closest that are breakbeat (chance 11 %): mean 80.8 %, **mean+std centred 88.8 %**, log-mean centred 87.3 %. DnB tracks: mean 98 %, mean+std centred 92 %. Chosen: mean+std centred (best average) |
| 2D layout: share of each track's 10 true neighbours that are map neighbours | PCA 26 %, UMAP 37–42 %, **t-SNE 46–47 %** (scikit-learn), numpy t-SNE 41.5 % vs scikit-learn 42.6 % on the same data |
| Map purity | Left half 277 breakbeat / 43 DnB, right half 8 breakbeat / 371 DnB |
| Example | Closest matches of Break The Box – *Test the Bass*: Stanton Warriors, Elite Force, Break The Box, Deekline & Wizard, Robosapiens, RMS & Peak, Hedflux |

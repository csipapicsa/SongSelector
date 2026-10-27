# Audio embeddings: reference from the DJ mix segmentation project

Status: research note only, nothing implemented yet. Planned use: compute an
embedding sequence for every track in the library (MP3/WAV/FLAC) for future
similarity and structure features.

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

## Notes for integrating into this app

- **Size:** CNN14 has about 81M parameters, and the 327 MB checkpoint alone is
  over 5× today's 59 MB exe. Ship it as an optional, separately downloaded
  component, not inside the exe.
- **Runtime:** `onnxruntime` with the existing `cnn14.onnx` avoids bundling PyTorch.
- **Storage:** a 6-minute track is 72 chunks × 2048 × 2 bytes ≈ 290 KB, so about
  1.5 GB for 5,000 tracks. Keep embeddings in files next to `library.sqlite`
  (one `.npy`/`.npz` per track, keyed by the track's `path_key`), or in a separate
  SQLite table of BLOBs. Do not put them in the main tracks table.
- **Background work:** extraction takes seconds per track, so it must run off the UI
  thread and be resumable (skip tracks whose embedding file exists and is newer
  than the audio file).

# Embedding models to compare with CNN14

Checked 2026-11-03 from the model pages (Hugging Face API, Zenodo, essentia.upf.edu). Anything not
read from a source is marked *to confirm* or *to measure*. This is not legal advice.

Setup this has to run on: GTX 1650 Ti (4 GB), 8 CPU threads. The app runs models with
onnxruntime (DirectML/CUDA/CPU) in a background process; PyTorch is **not** in the exe. Research
runs use the system Python, which has torch 2.5.1 (CUDA 12.1), transformers 5.14, scikit-learn
1.8, librosa and onnxruntime.

## Candidates

| Model | Trained on | Size | Embedding | Input | Licence | Runs as |
|---|---|---|---|---|---|---|
| **PANNs CNN14** (now) | AudioSet (general sounds) | 327 MB | 2048 / 5 s | 32 kHz, 5 s | weights CC BY 4.0 ([Zenodo](https://zenodo.org/records/3987831)), code MIT | ONNX (in the app) |
| **MSD-MusiCNN** (Essentia) | Million Song Dataset tags | 3.2 MB ONNX | 200 (penultimate layer) | 16 kHz, mel patches of 187 x 96 (about 3 s) | MTG models: CC BY-NC-SA 4.0 (per model: *to confirm*) | ONNX file on essentia.upf.edu |
| **Discogs-EffNet** (Essentia) | Discogs styles (400), music similarity | 18 MB (TensorFlow `.pb`; no ONNX on the site) | 1280 | 16 kHz, mel patches 128 x 96 | as above (*to confirm*) | TensorFlow, or convert to ONNX |
| **OpenL3, music** (mel128, emb512) | audio-video correspondence on music videos | 18.7 MB ONNX | 512 | 48 kHz, mel 199 x 128 | code MIT, weights CC BY 4.0 (*to confirm in its LICENSE*) | ONNX file on essentia.upf.edu |
| **MAEST 30 s** | Discogs styles | 347 MB, 87 M parameters | *to confirm* | 30 s | CC BY-NC-SA 4.0 | PyTorch (transformers) |
| **MERT-v1-95M** | self-supervised on 160 k h of music | 378 MB | *to confirm* | *to confirm* (24 kHz in the paper) | CC BY-NC 4.0 | PyTorch (transformers) |
| MERT-v1-330M | same, larger | 1.26 GB | *to confirm* | | CC BY-NC 4.0 | PyTorch |
| **LAION CLAP, music** | audio-text pairs | 776 MB | *to confirm* | *to confirm* | Apache 2.0 | PyTorch |
| MuQ (large) | self-supervised on music | 333 M parameters | *to confirm* | *to confirm* | CC BY-NC 4.0 | PyTorch |
| Jukebox | codified audio language model | billions of parameters | | | | **excluded**: far too heavy |

## Free to use? Lightweight?

- All are free to **download and use for your own research and personal use**. The catch is
  *non-commercial* terms (MTG/Essentia, MAEST, MERT, MuQ): fine for a personal tool, a problem only
  if the app were sold or bundled with such a model. CNN14 is not bundled either (the app asks for
  `cnn14.onnx`), so the same "bring your own model" setup would work for any of these.
  Only CNN14, OpenL3 and CLAP are under permissive terms.
- **Light:** MusiCNN (3 MB), OpenL3 and Discogs-EffNet (18 MB) are 20-100x smaller than CNN14 and
  should be faster. **Heavy:** MERT-95M, MAEST and CLAP are 350-780 MB, in the range of CNN14;
  MERT-330M, MuQ and Jukebox are bigger.
- CNN14 was chosen because it was already working and fast on this GPU (0.6 s model time per
  6-minute track), not because it was tested against these on music tasks.

## Integration cost, if one of them wins

| Model | What it takes |
|---|---|
| MusiCNN, OpenL3 | Already ONNX: the app's onnxruntime path works. The mel-spectrogram front end must be reproduced exactly (numpy/librosa; no new dependency). |
| Discogs-EffNet | Convert TensorFlow to ONNX once (tf2onnx), then as above. |
| MAEST, MERT, CLAP | Export the PyTorch model to ONNX (transformers models usually export), check it matches, or keep it out of the exe as an optional separate step. Exe size and DirectML operator support are *to measure*. |

## How they are compared

Same labels, same probes, same artist-grouped validation ([rating_color_plan.md](rating_color_plan.md)).
Speed on the same 10 library tracks (60.8 minutes of audio) used for the CNN14 measurements in
[audio_embeddings.md](audio_embeddings.md): model time per 6-minute track on the GPU and on 4 CPU
threads (decoding excluded), model load time, vector size per track.

Measured 2026-11-03 (GTX 1650 Ti through DirectML, one process, 4 tracks of 6-7 minutes, scaled to 6
minutes; the three small models' time includes their numpy spectrogram, which runs on the CPU):

| Model | GPU, s per 6-min track | Values per track (mean + std) | Notes |
|---|---|---|---|
| CNN14 | 0.6 (+ 0.8 decoding) | 4096 | from audio_embeddings.md, batches of 16 |
| MusiCNN | 1.1 | 400 | needed graph optimisation off on DirectML, otherwise onnxruntime falls back to the CPU (3x slower) |
| Discogs-EffNet | 0.4 | 2560 | the dynamic-batch ONNX (`discogs-effnet-bsdynamic-1.onnx`) |
| OpenL3 | 1.5 | 1024 | one 1 s window every 3 s; every second would be about 3x as long (the spectrogram is the cost) |
| MAEST, MERT, CLAP | *to measure* | | PyTorch; not integrated |

Reading: only Discogs-EffNet is faster than CNN14. MusiCNN and OpenL3 are small files but not faster here,
because their cost is the CPU spectrogram, not the network. Extracting all three for the whole library ran at
about 8 s per track and worker with two workers sharing the GPU and CPU (4+ hours for 3,600 tracks).

Front ends were reimplemented in numpy (Essentia has no Windows build here) and checked (`selfcheck.py`):
the MusiCNN spectrogram equals librosa's to 5e-7, and Discogs-EffNet names the right styles for tracks of
known genre ("Breaks" for breakbeat, "Drum n Bass / Jungle" for DnB, "House / Tech House" for house).
MusiCNN's 50 tags are all electronic / dance for electronic music, which is what its training data can say.

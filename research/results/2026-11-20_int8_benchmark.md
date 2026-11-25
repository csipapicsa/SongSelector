# int8 vs fp32: audio to embeddings (2026-11-20)

**Verdict: this int8 version is both slower and broken; not worth pursuing on the GPU, CPU left open.**
Why: `quantize_dynamic` with default settings also quantized the models' spectrogram front-end (the STFT is built
from convolutions with fixed Fourier kernels; see the `ConvInteger` nodes in the CUDA errors). Raw audio through an
8-bit STFT loses most of its detail, so the embeddings fell apart (window cosine 0.57 / 0.32 instead of the ~0.99 a
working int8 model keeps), and int8 convolutions (`ConvInteger`) are slow in onnxruntime, so it got slower too.
The GPU providers have no kernels for dynamic quantization (CUDA: none for ConvInteger; DirectML falls back), so
int8 cannot get faster there in this form. A fair CPU test would keep the front-end in float and quantize only
LAION's transformer (MatMul); not run (decided 2026-11-20: stop here unless the CPU matters later). CUDA fp32 was
much slower than DirectML in this environment (earlier measurements had them equal): likely the test set-up, not
investigated, since the app uses DirectML.

10 random tracks (seed 20261120), 54.5 min of audio; decoding (both rates, once): 22.4 s, not included below. Machine: Intel64 Family 6 Model 165 Stepping 2, GenuineIntel, 8 logical cores; GPU GeForce GTX 1650 Ti (4 GB). Times: all windows of all tracks, after a warm-up call; batch sizes as in the app.

| Model | Device | fp32 | int8 | int8 speed-up | fp32 per audio minute | int8 per audio minute |
|---|---|---|---|---|---|---|
| CNN14 | CPU (4 threads) (batch 1) | 66.1 s | 1110.9 s | 0.06x | 1.21 s | 20.39 s |
| CNN14 | GPU, DirectML (batch 8) | 5.9 s | 15.4 s | 0.38x | 0.11 s | 0.28 s |
| CNN14 | GPU, CUDA | onnxruntime.capi.onnxruntime_pybind11_state.NotImplemented: [ONNXRuntimeError] : 9 : NOT_IMPLEMENTED : Could not find an implementation for ConvInteger(10) node with name '/spectrogram_extractor/conv_imag/Conv_quant' | | | | |
| LAION CLAP | CPU (4 threads) (batch 1) | 52.4 s | 103.7 s | 0.51x | 0.96 s | 1.90 s |
| LAION CLAP | GPU, DirectML (batch 4) | 17.9 s | 22.8 s | 0.79x | 0.33 s | 0.42 s |
| LAION CLAP | GPU, CUDA | onnxruntime.capi.onnxruntime_pybind11_state.NotImplemented: [ONNXRuntimeError] : 9 : NOT_IMPLEMENTED : Could not find an implementation for ConvInteger(10) node with name '/Conv_1_quant' | | | | |

| Model | File size fp32 / int8 | Window cosine int8 vs fp32 (mean / min) | Top-10 neighbour windows kept | Same closest track |
|---|---|---|---|---|
| CNN14 | 327 / 82 MB | 0.5662 / 0.2724 | 4 % | 2/10 |
| LAION CLAP | 122 / 34 MB | 0.3164 / 0.0592 | 16 % | 3/10 |

## The percentages the app shows, fp32 vs int8 (CPU embeddings)

Description search: LAION, each prompt against each track (round(cosine x 100), as the List shows it); the text encoder is the same fp32 model for both. Closest matches: CNN14, each pair of tracks (centred mean+std vectors, as the map).

| Shown in the app | Pairs | Mean difference (points) | Largest | >= 2 points | >= 5 points | >= 10 points |
|---|---|---|---|---|---|---|
| Description search (LAION) | 120 | 17.02 | 45 | 92 % | 80 % | 68 % |
| Closest matches (CNN14) | 45 | 48.82 | 138 | 98 % | 96 % | 87 % |

Same top 3 tracks, in the same order, for 0 % of the prompts.

| Prompt | Its best track: fp32 | int8 |
|---|---|---|
| dark rolling drum and bass with a heavy reese bassline | 51 % | 38 % |
| hypnotic psychedelic techno with swirling acid synths | 41 % | 41 % |
| dark warehouse rave, pounding kick and distorted acid 303 line | 42 % | 33 % |
| euphoric trance with rising synth arpeggios and a big build-up | 46 % | 21 % |
| calm downtempo track with warm pads and soft piano | 45 % | 8 % |
| dreamy ambient electronica with gentle melodies | 34 % | 10 % |
| slow, mellow trip-hop beat with a jazzy feel | 44 % | 21 % |
| funky breakbeat with a groovy bassline and chopped drum breaks | 55 % | 12 % |
| big beat with funky samples, scratching and a bouncy break | 56 % | 17 % |
| nu-skool breaks with a rolling bassline and energetic drums | 58 % | 15 % |
| female vocal house track | 42 % | 9 % |
| aggressive distorted electro | 29 % | 18 % |

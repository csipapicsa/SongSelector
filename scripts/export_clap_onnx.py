"""Creates the CLAP model files SongSelector uses for audio similarity and free-text search.

CLAP (contrastive language-audio pretraining) has an audio encoder and a text encoder that map into the same space:
tracks get audio vectors in the background, a typed description gets a text vector, and the closest tracks win.
Two models (see docs/research/text_search_clap.md):

  laion   LAION CLAP `laion/clap-htsat-unfused` (Apache 2.0): 10 s windows at 48 kHz, 512 values
  ms      Microsoft CLAP 2023 (MS-PL): 7 s windows at 44.1 kHz, 1024 values

For each, three files go to the models folder (the app looks there; see songselector/core/embedding_models.py):
  clap-<name>-audio.onnx      raw mono audio (batch, samples) -> "embedding". LAION's log-mel spectrogram, computed
                              in Python by transformers, is built into the graph, so every model takes raw audio
  clap-<name>-text.onnx       input_ids, attention_mask -> "embedding"
  clap-<name>-tokenizer.json  for the `tokenizers` library (no transformers or PyTorch in the app)

Every export is checked against the PyTorch model it came from (and LAION's audio side against transformers' own
feature extractor) before it is written. Needs PyTorch >= 2.6, transformers < 5 and msclap, so run it in a separate
environment, e.g. the research one:

    python -m venv --system-site-packages .research_cache\\venv-clap
    .research_cache\\venv-clap\\Scripts\\python -m pip install msclap==1.3.4 "torch>=2.6" onnx onnxruntime
    .research_cache\\venv-clap\\Scripts\\python scripts\\export_clap_onnx.py            # both models
    .research_cache\\venv-clap\\Scripts\\python scripts\\export_clap_onnx.py --models laion

Weights are downloaded from Hugging Face on first use (615 MB for LAION, 690 MB + GPT-2 for Microsoft).
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
TOLERANCE = 2e-4  # largest allowed difference to PyTorch, on unit-length vectors


def unit(matrix):
    return matrix / np.linalg.norm(matrix, axis=-1, keepdims=True)


def compare(name, expected, actual):
    expected, actual = unit(np.asarray(expected, dtype=np.float64)), unit(np.asarray(actual, dtype=np.float64))
    difference = float(np.abs(expected - actual).max())
    cosine = float((expected * actual).sum(-1).min())
    print(f'  {name}: largest difference {difference:.1e}, lowest cosine {cosine:.6f}')
    if difference > TOLERANCE:
        sys.exit(f'{name}: the export does not match PyTorch.')


def export(module, inputs, path, input_names, dynamic_axes):
    import torch
    with torch.no_grad():
        torch.onnx.export(module, inputs, str(path), input_names=input_names, output_names=['embedding'],
                          dynamic_axes=dynamic_axes, opset_version=17, dynamo=False)


def run_onnx(path, feeds):
    import onnxruntime
    session = onnxruntime.InferenceSession(str(path), providers=['CPUExecutionProvider'])
    return session.run(['embedding'], feeds)[0]


def test_audio(rate, seconds, count=3):
    """Real-ish test audio: noise bursts and tones, so the spectrogram is not flat."""
    rng = np.random.default_rng(0)
    t = np.arange(int(rate * seconds)) / rate
    clips = [0.3 * np.sin(2 * np.pi * (110 * (i + 1)) * t) * (1 + np.sin(2 * np.pi * 2 * t)) / 2
             + 0.1 * rng.standard_normal(len(t)) for i in range(count)]
    return np.stack(clips).astype(np.float32)


PROMPTS = ['This audio is a drum and bass song.', 'calm downtempo track with warm pads and soft piano',
           'funky breakbeat']


# ---- LAION CLAP ---------------------------------------------------------------------------------------------

def laion(out):
    import torch
    from transformers import AutoTokenizer, ClapModel, ClapProcessor

    repo = 'laion/clap-htsat-unfused'
    model = ClapModel.from_pretrained(repo).eval()
    processor = ClapProcessor.from_pretrained(repo)
    extractor = processor.feature_extractor
    rate, samples = extractor.sampling_rate, extractor.nb_max_samples  # 48 kHz, 10 s

    class Audio(torch.nn.Module):
        """Raw audio -> transformers' log-mel features (as a fixed-weight graph) -> audio embedding."""

        def __init__(self):
            super().__init__()
            n_fft, self.hop = extractor.fft_window_size, extractor.hop_length  # 1024, 480
            window = torch.hann_window(n_fft, periodic=True, dtype=torch.float64)
            frequencies = torch.arange(n_fft // 2 + 1, dtype=torch.float64)[:, None]
            phase = 2 * np.pi * frequencies * torch.arange(n_fft, dtype=torch.float64)[None, :] / n_fft
            # The DFT as two convolutions (real and imaginary part), like torchlibrosa's STFT in CNN14.
            self.register_buffer('real', (torch.cos(phase) * window)[:, None, :].float())
            self.register_buffer('imag', (-torch.sin(phase) * window)[:, None, :].float())
            self.register_buffer('mel', torch.tensor(extractor.mel_filters_slaney, dtype=torch.float32))  # (513, 64)
            self.pad = n_fft // 2
            self.clap = model

        def forward(self, audio):
            x = torch.nn.functional.pad(audio[:, None, :], (self.pad, self.pad), mode='reflect')  # center=True
            real = torch.nn.functional.conv1d(x, self.real, stride=self.hop)
            imag = torch.nn.functional.conv1d(x, self.imag, stride=self.hop)
            power = (real * real + imag * imag).transpose(1, 2)               # (batch, frames, 513)
            log_mel = 10 * torch.log10(torch.clamp(power @ self.mel, min=1e-10))  # dB, as log_mel="dB"
            return self.clap.get_audio_features(input_features=log_mel[:, None])

    class Text(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.clap = model

        def forward(self, input_ids, attention_mask):
            return self.clap.get_text_features(input_ids=input_ids, attention_mask=attention_mask)

    print('LAION CLAP: audio')
    audio = test_audio(rate, samples / rate)
    with torch.no_grad():
        features = extractor(list(audio), sampling_rate=rate, return_tensors='pt')
        reference = model.get_audio_features(**features).numpy()     # transformers' own pipeline
        wrapped = Audio().eval()
        compare('graph spectrogram vs transformers', reference, wrapped(torch.from_numpy(audio)).numpy())
    audio_path = out / 'clap-laion-audio.onnx'
    export(wrapped, (torch.from_numpy(audio[:1]),), audio_path, ['audio'], {'audio': {0: 'batch'}, 'embedding': {0: 'batch'}})
    compare('ONNX audio vs transformers', reference, run_onnx(audio_path, {'audio': audio}))

    print('LAION CLAP: text')
    tokenizer = AutoTokenizer.from_pretrained(repo, use_fast=True)
    tokenizer_path = out / 'clap-laion-tokenizer.json'
    tokenizer.backend_tokenizer.save(str(tokenizer_path))
    text = Text().eval()
    sample = tokenizer(PROMPTS[0], return_tensors='pt')
    export(text, (sample['input_ids'], sample['attention_mask']), out / 'clap-laion-text.onnx',
           ['input_ids', 'attention_mask'],
           {'input_ids': {0: 'batch', 1: 'tokens'}, 'attention_mask': {0: 'batch', 1: 'tokens'}, 'embedding': {0: 'batch'}})
    check_text(tokenizer_path, out / 'clap-laion-text.onnx', lambda prompt: _torch_text(text, tokenizer, prompt),
               pad_to=None, suffix='')


def _torch_text(module, tokenizer, prompt):
    import torch
    tokens = tokenizer(prompt, return_tensors='pt')
    with torch.no_grad():
        return module(tokens['input_ids'], tokens['attention_mask']).numpy()[0]


# ---- Microsoft CLAP 2023 ------------------------------------------------------------------------------------

MS_TEXT_LENGTH = 77
MS_SUFFIX = ' <|endoftext|>'


def _patch_window_reverse():
    """msclap's HTSAT computes the batch size with int(windows.shape[0] / ...). Tracing turns that int() into a
    constant, so the ONNX graph only works for the batch size it was exported with (batch 3 gave cosine 0.62
    against PyTorch). Same arithmetic, with the batch size left to reshape (-1); checked against msclap's output."""
    import msclap.models.htsat as htsat

    def window_reverse(windows, window_size, H, W):
        channels = windows.shape[-1]
        x = windows.view(-1, H // window_size, W // window_size, window_size, window_size, channels)
        return x.permute(0, 1, 3, 2, 4, 5).contiguous().view(-1, H, W, channels)

    htsat.window_reverse = window_reverse


def _traceable_attention_masks():
    """transformers >= 4.5x builds attention masks with torch.vmap on PyTorch >= 2.6, which the ONNX tracer cannot
    follow ("invalid unordered_map key"). Its implementation for older PyTorch builds the same mask without vmap;
    the text check against msclap's own output confirms the export."""
    from transformers import masking_utils
    masking_utils.sdpa_mask = masking_utils.sdpa_mask_older_torch
    masking_utils.ALL_MASK_ATTENTION_FUNCTIONS['sdpa'] = masking_utils.sdpa_mask_older_torch


def ms(out):
    import torch
    from msclap import CLAP

    wrapper = CLAP(version='2023', use_cuda=False)
    clap, rate = wrapper.clap.eval(), wrapper.args.sampling_rate
    samples = rate * wrapper.args.duration

    class Audio(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = clap.audio_encoder

        def forward(self, audio):
            return self.encoder(audio)[0]

    class Text(torch.nn.Module):
        """GPT-2 + projection; the embedding is taken at the last real token, as msclap does (pad id 0)."""

        def __init__(self):
            super().__init__()
            self.encoder = clap.caption_encoder

        def forward(self, input_ids, attention_mask):
            # msclap's TextEncoder.forward for GPT-2, written out with use_cache=False: the key/value cache
            # object that GPT-2 returns by default cannot be traced into ONNX.
            hidden = self.encoder.base(input_ids=input_ids, attention_mask=attention_mask, use_cache=False)[0]
            last = torch.ne(input_ids, 0).sum(-1) - 1
            return self.encoder.projection(hidden[torch.arange(input_ids.shape[0]), last])

    print('Microsoft CLAP 2023: audio')
    audio = test_audio(rate, samples / rate)
    module = Audio().eval()
    with torch.no_grad():
        reference = module(torch.from_numpy(audio)).numpy()  # with msclap's own code, before the patch below
    _patch_window_reverse()
    audio_path = out / 'clap-ms-audio.onnx'
    export(module, (torch.from_numpy(audio[:1]),), audio_path, ['audio'], {'audio': {0: 'batch'}, 'embedding': {0: 'batch'}})
    compare('ONNX audio vs PyTorch', reference, run_onnx(audio_path, {'audio': audio}))

    print('Microsoft CLAP 2023: text')
    tokenizer_path = out / 'clap-ms-tokenizer.json'
    wrapper.tokenizer.backend_tokenizer.save(str(tokenizer_path))
    _traceable_attention_masks()
    text = Text().eval()
    sample = wrapper.preprocess_text([PROMPTS[0]])
    export(text, (sample['input_ids'], sample['attention_mask']), out / 'clap-ms-text.onnx',
           ['input_ids', 'attention_mask'], {'input_ids': {0: 'batch'}, 'attention_mask': {0: 'batch'}, 'embedding': {0: 'batch'}})

    def reference_text(prompt):
        return wrapper.get_text_embeddings([prompt]).numpy()[0]
    check_text(tokenizer_path, out / 'clap-ms-text.onnx', reference_text, pad_to=MS_TEXT_LENGTH, suffix=MS_SUFFIX)


# ---- Text through the app's path: tokenizers + ONNX ---------------------------------------------------------

def check_text(tokenizer_path, model_path, reference, pad_to, suffix):
    """Tokenise as the app will (the tokenizers library, songselector.core.text_search) and compare."""
    sys.path.insert(0, str(REPO / 'src'))
    from songselector.core.text_search import tokenize
    from tokenizers import Tokenizer
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    expected, actual = [], []
    for prompt in PROMPTS:
        ids, mask = tokenize(tokenizer, prompt, pad_to=pad_to, suffix=suffix)
        actual.append(run_onnx(model_path, {'input_ids': ids, 'attention_mask': mask})[0])
        expected.append(reference(prompt))
    compare('ONNX text (app tokenizer) vs PyTorch', np.stack(expected), np.stack(actual))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--models', nargs='+', choices=['laion', 'ms'], default=['laion', 'ms'])
    parser.add_argument('--out', type=Path, default=REPO / '.appdata' / 'models',
                        help='models folder (default: where the app looks when run from source)')
    args = parser.parse_args()
    os.environ.setdefault('TRANSFORMERS_VERBOSITY', 'error')
    args.out.mkdir(parents=True, exist_ok=True)
    for name in args.models:
        {'laion': laion, 'ms': ms}[name](args.out)
    for path in sorted(args.out.glob('clap-*')):
        print(f'{path.name}: {path.stat().st_size / 1e6:.0f} MB')


if __name__ == '__main__':
    main()

"""Student audio encoders: one raw 10 s window at 24 kHz -> a 512-d vector in AllMusicCaps' audio space.

The log-mel front end is part of each network, so it is also inside the exported ONNX file. A student then has the
same contract as every model in the app (core/embedding_models.py): input "audio" (batch, samples), output
"embedding" (batch, 512), and adding one to the app is a new model entry, not new preprocessing code.

Candidates (README.md, "Experiment matrix"; letters as in the distillation brief):
    mfcc40-mlp      B  MFCC mean/std over time -> MLP. Barely more than the front end: the cost floor.
    cnn4-small-64   D  64-bin log-mel, 4 conv blocks (16-128 channels).
    cnn4-64         D  64-bin log-mel, 4 conv blocks (32-256 channels), the brief's first serious baseline.
    mnv3s-128       E  128-bin log-mel, MobileNetV3-Small (depthwise convolutions), 1-channel input.

Phase 2, model structure (one change each from cnn4-small-64, README "Phase 2"):
    cnn4-small-64-tcn    + 4 dilated temporal blocks after the CNN: sees ~5.3 s instead of ~0.46 s per frame
    cnn4-small-64-attn   attentive statistics pooling over time instead of the plain mean and std
    cnn4-small-128       128 mel bands instead of 64 (needs mel128.npy: prepare_data.py --mels 128)

    python students.py            export every student with random weights to .research_cache/distill/onnx/
"""
import argparse
import math
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DIM, RATE, WINDOW, WORK  # noqa: E402

ONNX_DIR = WORK / 'onnx'


# ---- Front end -----------------------------------------------------------------------------------------------

def mel_filterbank(rate, n_fft, n_mels, fmin, fmax):
    """(n_fft // 2 + 1, n_mels) triangular filters on the HTK mel scale."""
    def to_mel(hz):
        return 2595.0 * np.log10(1.0 + np.asarray(hz) / 700.0)

    def to_hz(mel):
        return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)

    bins = np.linspace(0, rate / 2, n_fft // 2 + 1)
    edges = to_hz(np.linspace(to_mel(fmin), to_mel(fmax), n_mels + 2))
    rising = (bins[None, :] - edges[:-2, None]) / (edges[1:-1] - edges[:-2])[:, None]
    falling = (edges[2:, None] - bins[None, :]) / (edges[2:] - edges[1:-1])[:, None]
    return np.maximum(0.0, np.minimum(rising, falling)).T.astype(np.float32)


def dct_matrix(n_in, n_out):
    """(n_in, n_out) orthonormal DCT-II: log-mel @ dct = MFCC."""
    n, k = np.arange(n_in)[:, None], np.arange(n_out)[None, :]
    matrix = np.cos(math.pi / n_in * (n + 0.5) * k) * math.sqrt(2.0 / n_in)
    matrix[:, 0] /= math.sqrt(2.0)
    return matrix.astype(np.float32)


class LogMel(nn.Module):
    """(batch, samples) -> (batch, n_mels, frames) log power. 1024-point Hann window (43 ms, so 23 Hz bins: the
    sub-bass of drum and bass gets several mel bands), 10 ms hop: a 10 s window gives 1001 frames."""

    def __init__(self, n_mels=64, n_fft=1024, hop=240, fmin=30.0, fmax=11000.0):
        super().__init__()
        self.n_fft, self.hop = n_fft, hop
        self.register_buffer('window', torch.hann_window(n_fft), persistent=False)
        mel = torch.from_numpy(mel_filterbank(RATE, n_fft, n_mels, fmin, fmax)).T.contiguous()
        self.register_buffer('mel', mel, persistent=False)    # (n_mels, n_freq)

    def forward(self, audio):
        # Zero padding by hand instead of center=True: the ONNX STFT op has no centring.
        audio = F.pad(audio, (self.n_fft // 2, self.n_fft // 2))
        spec = torch.stft(audio, self.n_fft, hop_length=self.hop, window=self.window, center=False,
                          return_complex=False)               # (batch, n_freq, frames, 2): real, imaginary
        power = spec.pow(2).sum(-1)
        return torch.log(torch.clamp(torch.matmul(self.mel, power), min=1e-10))


def mean_std(x, dim):
    """Mean and standard deviation over `dim`, side by side: keeps how much a feature varies, not only its level."""
    return torch.cat([x.mean(dim), torch.sqrt(x.var(dim, unbiased=False) + 1e-5)], dim=-1)


# ---- Students ------------------------------------------------------------------------------------------------

class Student(nn.Module):
    """Every student: forward(audio) = embed_mel(frontend(audio)). The front end has no learned weights, so training
    can start from cached log-mels (embed_mel) and the exported model (forward) still computes exactly the same."""

    def __init__(self, n_mels):
        super().__init__()
        self.n_mels = n_mels
        self.frontend = LogMel(n_mels)

    def forward(self, audio):
        return self.embed_mel(self.frontend(audio))


class MfccMlp(Student):
    def __init__(self, n_mels=64, n_mfcc=40, hidden=512, dim=DIM):
        super().__init__(n_mels)
        self.register_buffer('dct', torch.from_numpy(dct_matrix(n_mels, n_mfcc)), persistent=False)
        self.norm = nn.BatchNorm1d(2 * n_mfcc)
        self.mlp = nn.Sequential(nn.Linear(2 * n_mfcc, hidden), nn.ReLU(inplace=True), nn.Linear(hidden, dim))

    def embed_mel(self, mel):
        mfcc = torch.matmul(mel.transpose(1, 2), self.dct)   # (batch, frames, n_mfcc)
        return self.mlp(self.norm(mean_std(mfcc, 1)))


class ConvBlock(nn.Sequential):
    def __init__(self, cin, cout, pool=(2, 2)):
        super().__init__(nn.Conv2d(cin, cout, 3, padding=1, bias=False), nn.BatchNorm2d(cout),
                         nn.ReLU(inplace=True), nn.AvgPool2d(pool))


class TemporalBlock(nn.Module):
    """Residual, dilated, depthwise-separable 1-D convolution over time (as in TCN / Conv-TasNet): kernel 3 with
    dilation d lets each frame see d frames further on both sides. The last BatchNorm's scale starts at zero (the
    "zero-init residual" trick), so a new block is the identity and the student starts as its twin without blocks.
    The ReLU sits before the pointwise convolution: a ReLU after a zero-scaled BatchNorm would get no gradient."""

    def __init__(self, channels, dilation):
        super().__init__()
        self.depthwise = nn.Conv1d(channels, channels, 3, padding=dilation, dilation=dilation, groups=channels,
                                   bias=False)
        self.norm1 = nn.BatchNorm1d(channels)
        self.pointwise = nn.Conv1d(channels, channels, 1, bias=False)
        self.norm2 = nn.BatchNorm1d(channels)
        nn.init.zeros_(self.norm2.weight)

    def forward(self, x):   # (batch, channels, frames), same shape out
        return x + self.norm2(self.pointwise(F.relu(self.norm1(self.depthwise(x)))))


class MeanStd(nn.Module):
    def forward(self, x):   # (batch, channels, frames) -> (batch, 2 * channels)
        return mean_std(x, -1)


class AttentiveStats(nn.Module):
    """Attentive statistics pooling (Okabe et al. 2018, as in ECAPA-TDNN): a softmax over time per channel weights the
    frames, then the weighted mean and standard deviation. The plain mean counts a breakdown as much as a drop. The
    last layer starts at zero, i.e. equal weights: exactly MeanStd, so training starts from the plain student."""

    def __init__(self, channels, hidden=64):
        super().__init__()
        self.score = nn.Sequential(nn.Conv1d(channels, hidden, 1), nn.Tanh(), nn.Conv1d(hidden, channels, 1))
        nn.init.zeros_(self.score[-1].weight)
        nn.init.zeros_(self.score[-1].bias)

    def forward(self, x):   # (batch, channels, frames) -> (batch, 2 * channels)
        weight = torch.softmax(self.score(x), dim=-1)
        mean = (weight * x).sum(-1)
        var = torch.clamp((weight * x * x).sum(-1) - mean * mean, min=0.0)
        return torch.cat([mean, torch.sqrt(var + 1e-5)], dim=-1)


class Cnn4(Student):
    """Log-mel image -> 4 conv blocks (each halves frequency and time) -> mean over frequency -> optional temporal
    blocks -> statistics over time (mean and std, or attentive) -> linear projection to the teacher's 512 dimensions.

    After the 4 blocks a frame stands for 16 input frames (160 ms) and sees 46 of them (~0.46 s, about one beat), so
    the plain CNN is a "bag of beats": the order of beats, bars and phrases is lost in the mean over time, while the
    teacher (a transformer) relates every part of the 10 s window to every other. temporal=(1, 2, 4, 8) widens the
    view by 2 * (1 + 2 + 4 + 8) = 30 frames (+4.8 s, two to three bars at 128-174 BPM). Without temporal blocks and
    with mean pooling the state dict is the same as before, so earlier runs still load."""

    def __init__(self, channels=(32, 64, 128, 256), n_mels=64, dim=DIM, temporal=(), pooling='mean'):
        super().__init__(n_mels)
        self.norm = nn.BatchNorm1d(n_mels)          # per mel band, learned (PANNs' bn0)
        blocks, cin = [], 1
        for cout in channels:
            blocks.append(ConvBlock(cin, cout))
            cin = cout
        self.blocks = nn.Sequential(*blocks)
        self.temporal = nn.Sequential(*[TemporalBlock(cin, d) for d in temporal])   # empty: no parameters
        self.pool = AttentiveStats(cin) if pooling == 'attentive' else MeanStd()
        self.head = nn.Linear(2 * cin, dim)

    def embed_mel(self, mel):
        x = self.blocks(self.norm(mel).unsqueeze(1))   # (batch, channels, mels / 16, frames / 16)
        return self.head(self.pool(self.temporal(x.mean(2))))


class MobileNetV3S(Student):
    """torchvision's MobileNetV3-Small body on a 1-channel log-mel image, with the same pooling and head as Cnn4."""

    def __init__(self, n_mels=128, dim=DIM):
        super().__init__(n_mels)
        from torchvision.models import mobilenet_v3_small
        body = mobilenet_v3_small(weights=None).features
        first = body[0][0]
        body[0][0] = nn.Conv2d(1, first.out_channels, first.kernel_size, first.stride, first.padding, bias=False)
        self.norm = nn.BatchNorm1d(n_mels)
        self.body = body
        self.head = nn.Linear(2 * 576, dim)

    def embed_mel(self, mel):
        x = self.body(self.norm(mel).unsqueeze(1))
        return self.head(mean_std(x.mean(2), -1))


STUDENTS = {
    'mfcc40-mlp': lambda: MfccMlp(),
    'cnn4-small-64': lambda: Cnn4((16, 32, 64, 128), 64),
    'cnn4-64': lambda: Cnn4((32, 64, 128, 256), 64),
    'mnv3s-128': lambda: MobileNetV3S(128),
    # Phase 2, model structure: one change each from cnn4-small-64
    'cnn4-small-64-tcn': lambda: Cnn4((16, 32, 64, 128), 64, temporal=(1, 2, 4, 8)),
    'cnn4-small-64-attn': lambda: Cnn4((16, 32, 64, 128), 64, pooling='attentive'),
    'cnn4-small-128': lambda: Cnn4((16, 32, 64, 128), 128),
}


def parameters(model):
    return sum(p.numel() for p in model.parameters())


# ---- ONNX ----------------------------------------------------------------------------------------------------

def export(model, path):
    """ONNX with the app's names ("audio" -> "embedding") and a dynamic batch, checked against PyTorch."""
    import onnxruntime
    model.eval()
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(model, (torch.zeros(1, WINDOW),), str(path), input_names=['audio'], output_names=['embedding'],
                      dynamic_axes={'audio': {0: 'batch'}, 'embedding': {0: 'batch'}}, opset_version=17,
                      dynamo=False)
    audio = np.random.default_rng(0).uniform(-0.3, 0.3, (3, WINDOW)).astype(np.float32)
    with torch.inference_mode():
        expected = model(torch.from_numpy(audio)).numpy()
    session = onnxruntime.InferenceSession(str(path), providers=['CPUExecutionProvider'])
    actual = session.run(['embedding'], {'audio': audio})[0]
    cosine = (actual * expected).sum(1) / (np.linalg.norm(actual, axis=1) * np.linalg.norm(expected, axis=1))
    return {'max_abs_diff': float(np.abs(actual - expected).max()), 'min_cosine': float(cosine.min()),
            'shape': list(actual.shape)}


def main():
    parser = argparse.ArgumentParser(description='Export the students with random weights (for speed tests).')
    parser.add_argument('--students', nargs='+', default=list(STUDENTS), choices=list(STUDENTS))
    args = parser.parse_args()
    torch.manual_seed(0)
    for name in args.students:
        model = STUDENTS[name]()
        path = ONNX_DIR / f'{name}.onnx'
        check = export(model, path)
        ok = check['shape'] == [3, DIM] and check['min_cosine'] > 0.9999
        print(f"{name:15s} {parameters(model) / 1e6:5.2f} M params  {path.stat().st_size / 1e6:5.1f} MB  "
              f"ONNX vs PyTorch: max diff {check['max_abs_diff']:.1e}, cosine {check['min_cosine']:.6f}"
              f"{'' if ok else '  <-- MISMATCH'}")
        if not ok:
            sys.exit(1)


if __name__ == '__main__':
    main()

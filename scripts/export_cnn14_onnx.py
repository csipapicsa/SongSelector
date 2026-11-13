"""Creates cnn14.onnx, the audio embedding model SongSelector uses, from the published PANNs checkpoint.

The model is not in the repo or the exe (327 MB). This script downloads the CNN14 checkpoint of
PANNs (Kong et al., 2020; weights CC BY 4.0, https://zenodo.org/records/3987831), checks its
SHA-256, exports it to ONNX and checks that onnxruntime gives the same embeddings as PyTorch.

It needs PyTorch, which the app itself does not, so run it in a separate environment:

    python -m venv .export-venv
    .\\.export-venv\\Scripts\\python -m pip install torch panns-inference==0.1.1 onnx onnxruntime
    .\\.export-venv\\Scripts\\python scripts\\export_cnn14_onnx.py

The default output, .appdata\\models\\cnn14.onnx, is where the app looks when it runs from source.
For the exe, put the file in a "models" folder next to the exe, or pick it with
Analysis -> Choose embedding model...
"""
import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

import numpy as np

CHECKPOINT_URL = 'https://zenodo.org/records/3987831/files/Cnn14_mAP=0.431.pth?download=1'
CHECKPOINT_SHA256 = '0dc499e40e9761ef5ea061ffc77697697f277f6a960894903df3ada000e34b31'
SAMPLE_RATE = 32000
CHUNK_SAMPLES = SAMPLE_RATE * 5  # the app embeds 5-second chunks
REPO = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as file:
        for block in iter(lambda: file.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def checkpoint_file(path):
    """The checkpoint at path, downloaded first if missing. Fails if it is not the published file."""
    path = Path(path)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f'Downloading the CNN14 checkpoint (327 MB) to {path} ...')
        partial = path.with_name(path.name + '.part')
        urllib.request.urlretrieve(CHECKPOINT_URL, partial)
        partial.replace(path)
    actual = sha256(path)
    if actual != CHECKPOINT_SHA256:
        sys.exit(f'{path} has SHA-256 {actual}, expected {CHECKPOINT_SHA256}. Delete it and run again.')
    return path


def load_model(checkpoint):
    import torch
    from panns_inference.models import Cnn14
    # The configuration CNN14 was trained with (as panns_inference.AudioTagging builds it).
    model = Cnn14(sample_rate=SAMPLE_RATE, window_size=1024, hop_size=320, mel_bins=64, fmin=50, fmax=14000,
                  classes_num=527)
    model.load_state_dict(torch.load(checkpoint, map_location='cpu', weights_only=True)['model'])
    return model.eval()


def export(model, out):
    import torch
    out.parent.mkdir(parents=True, exist_ok=True)
    example = torch.zeros(1, CHUNK_SAMPLES)
    # Names the app relies on: input "audio", output "embedding" (2048 values per chunk). The batch
    # dimension stays dynamic because the app sends several chunks per call on the GPU.
    torch.onnx.export(model, (example,), str(out), input_names=['audio'],
                      output_names=['clipwise_output', 'embedding'],
                      dynamic_axes={'audio': {0: 'batch'}, 'clipwise_output': {0: 'batch'}, 'embedding': {0: 'batch'}},
                      opset_version=17, dynamo=False)


def check(model, out):
    """Same embeddings from onnxruntime as from PyTorch, for a batch of random 'audio'."""
    import onnxruntime
    import torch
    audio = np.random.default_rng(0).uniform(-0.5, 0.5, (3, CHUNK_SAMPLES)).astype(np.float32)
    with torch.no_grad():
        expected = model(torch.from_numpy(audio))['embedding'].numpy()
    session = onnxruntime.InferenceSession(str(out), providers=['CPUExecutionProvider'])
    actual = session.run(['embedding'], {'audio': audio})[0]
    difference = float(np.abs(actual - expected).max())
    print(f'Largest difference to PyTorch: {difference:.2e} (shape {actual.shape})')
    if actual.shape != (3, 2048) or difference > 1e-4:
        sys.exit('The exported model does not match PyTorch.')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--checkpoint', type=Path, default=Path.home() / 'panns_data' / 'Cnn14_mAP=0.431.pth',
                        help='downloaded here if missing (default: where panns_inference keeps it)')
    parser.add_argument('--out', type=Path, default=REPO / '.appdata' / 'models' / 'cnn14.onnx')
    args = parser.parse_args()
    model = load_model(checkpoint_file(args.checkpoint))
    export(model, args.out)
    check(model, args.out)
    print(f'Wrote {args.out} ({args.out.stat().st_size / 1e6:.0f} MB)')


if __name__ == '__main__':
    main()

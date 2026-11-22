"""ONNX export of MTG's AllMusicCaps CLAP (`all_layers`) and a check on the app's runtime (see allmusiccaps_clap.md).

Two steps, two environments:

    # 1. export + PyTorch references on real test-set windows (research venv: torch, amclap)
    .research_cache\\venv-clap\\Scripts\\python docs\\research\\experiments\\clap\\amclap_onnx.py export
    # 2. parity and speed with the app's onnxruntime-directml and session settings (the app's venv)
    .venv\\Scripts\\python docs\\research\\experiments\\clap\\amclap_onnx.py check

Output: .research_cache/onnx/amc-all-layers/{audio.onnx, text.onnx, tokenizer.json, reference.npz}; `check` prints a
JSON line per provider. Each DirectML batch size is timed in a fresh process (`time BATCH`): in one process the
numbers drifted, and an earlier run that went on to LAION at batch 8+ hung the 4 GB GPU.
"""
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[4]
OUT = REPO / '.research_cache' / 'onnx' / 'amc-all-layers'
MODEL_ID = 'mtg-upf/allmusiccaps_all_layers'
RATE, WINDOW = 24000, 24000 * 10
DML_OPTIONS = {'performance_preference': 'high_performance', 'device_filter': 'gpu'}  # as core/embeddings.py
PROMPTS = ['dark rolling drum and bass with a heavy reese bassline', 'breakbeat', 'This audio is a house song.',
           'A laid-back downtempo track with slow beats and a warm, mellow atmosphere.', 'jungle', 'acid',
           'Robotic electro with 808 drum machines and funky synth bass.', 'female vocals']


def export():
    import random
    import sqlite3
    os.environ['HF_HOME'] = str(REPO / '.research_cache' / 'hf')
    os.environ['HF_HUB_OFFLINE'] = '1'
    import torch
    from amclap import get_model
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from benchmark_cpu import decode, windows_of

    OUT.mkdir(parents=True, exist_ok=True)
    model = get_model(model_id=MODEL_ID, device='cpu')

    class Audio(torch.nn.Module):  # waveform (batch, 240000) at 24 kHz -> (batch, 512)
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, audio):
            return self.m.forward_audio(audio)

    class Text(torch.nn.Module):  # MPNet token ids -> (batch, 512); eval-mode forward_text goes through encode()
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, input_ids, attention_mask):
            features = self.m.text_encoder.model({'input_ids': input_ids, 'attention_mask': attention_mask})
            return self.m.proj_t(features['sentence_embedding'])

    audio_net, text_net = Audio(model).eval(), Text(model).eval()
    sentence_model = model.text_encoder.model
    torch.onnx.export(audio_net, (torch.randn(2, WINDOW) * 0.1,), OUT / 'audio.onnx', input_names=['audio'],
                      output_names=['embedding'], dynamic_axes={'audio': {0: 'batch'}, 'embedding': {0: 'batch'}},
                      opset_version=17, dynamo=False)
    tokens = sentence_model.tokenize(['a warm-up prompt', 'b'])
    torch.onnx.export(text_net, (tokens['input_ids'], tokens['attention_mask']), OUT / 'text.onnx',
                      input_names=['input_ids', 'attention_mask'], output_names=['embedding'], opset_version=17,
                      dynamo=False, dynamic_axes={'input_ids': {0: 'batch', 1: 'tokens'},
                                                  'attention_mask': {0: 'batch', 1: 'tokens'}, 'embedding': {0: 'batch'}})
    sentence_model.tokenizer.backend_tokenizer.save(str(OUT / 'tokenizer.json'))

    # References: 4 random windows from each of 6 random test-set tracks (extract_embeddings.py's track list).
    keys = json.loads((REPO / '.research_cache' / 'clap' / 'tracks.json').read_text())
    with sqlite3.connect(REPO / '.research_cache' / 'clap' / 'library.sqlite') as connection:
        paths = dict(connection.execute('SELECT path_key, file_path FROM tracks'))
    rng = random.Random(1)
    windows = []
    for key in rng.sample(keys, 6):
        track = windows_of(decode(paths[key], RATE), WINDOW)
        windows += [track[i] for i in rng.sample(range(len(track)), min(4, len(track)))]
    windows = np.stack(windows).astype(np.float32)
    with torch.inference_mode():
        audio_ref = np.concatenate([audio_net(torch.from_numpy(windows[i:i + 8])).numpy()
                                    for i in range(0, len(windows), 8)])
        text_ref = model.forward_text(PROMPTS).numpy()
    np.savez(OUT / 'reference.npz', windows=windows, audio_ref=audio_ref, text_ref=text_ref)
    print({path.name: f'{path.stat().st_size / 1e6:.0f} MB' for path in OUT.iterdir()})


def session_options(onnxruntime):
    """The app's settings (OnnxEmbedder._options)."""
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = max(1, (os.cpu_count() or 2) // 2)
    options.inter_op_num_threads = 1
    options.enable_mem_pattern = False
    options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
    return options


def providers_for(name):
    return [('DmlExecutionProvider', DML_OPTIONS)] if name == 'dml' else ['CPUExecutionProvider']


def cosine(a, b):
    return (a * b).sum(1) / np.linalg.norm(a, axis=1) / np.linalg.norm(b, axis=1)


def check():
    import onnxruntime
    from tokenizers import Tokenizer
    reference = np.load(OUT / 'reference.npz')
    windows, audio_ref, text_ref = reference['windows'], reference['audio_ref'], reference['text_ref']
    tokenizer = Tokenizer.from_file(str(OUT / 'tokenizer.json'))
    for name in ('dml', 'cpu'):
        options = session_options(onnxruntime)
        audio = onnxruntime.InferenceSession(str(OUT / 'audio.onnx'), options, providers=providers_for(name))
        text = onnxruntime.InferenceSession(str(OUT / 'text.onnx'), options, providers=providers_for(name))
        got = np.concatenate([audio.run(None, {'audio': windows[i:i + 4]})[0] for i in range(0, len(windows), 4)])
        queries = []
        for prompt in PROMPTS:
            encoding = tokenizer.encode(prompt)
            queries.append(text.run(None, {'input_ids': np.array([encoding.ids], dtype=np.int64),
                                           'attention_mask': np.array([encoding.attention_mask], dtype=np.int64)})[0][0])
        queries = np.stack(queries)
        rank_onnx = (queries @ got.T).argmax(1)
        rank_torch = (text_ref @ audio_ref.T).argmax(1)
        print(json.dumps({
            'provider': audio.get_providers()[0], 'onnxruntime': onnxruntime.__version__,
            'audio_min_cosine': round(float(cosine(got, audio_ref).min()), 6),
            'audio_max_abs_diff': float(np.abs(got - audio_ref).max()),
            'text_min_cosine': round(float(cosine(queries, text_ref).min()), 6),
            'same_best_window_for_every_prompt': bool((rank_onnx == rank_torch).all()),
        }), flush=True)
    for batch in (1, 2, 4, 8, 16):
        subprocess.run([sys.executable, __file__, 'time', str(batch)], check=True)


def time_batch(batch):
    import onnxruntime
    session = onnxruntime.InferenceSession(str(OUT / 'audio.onnx'), session_options(onnxruntime),
                                           providers=providers_for('dml'))
    audio = (np.random.default_rng(0).standard_normal((batch, WINDOW)) * 0.1).astype(np.float32)
    for _ in range(3):
        session.run(None, {'audio': audio})
    times = []
    for _ in range(20):
        started = time.perf_counter()
        session.run(None, {'audio': audio})
        times.append(time.perf_counter() - started)
    print(f'DirectML batch {batch}: {statistics.median(times) / batch * 1000:.1f} ms per window', flush=True)


if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv) > 1 else ''
    if command == 'export':
        export()
    elif command == 'check':
        check()
    elif command == 'time':
        time_batch(int(sys.argv[2]))
    else:
        sys.exit(__doc__)

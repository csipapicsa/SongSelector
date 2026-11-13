"""Times CNN14 on one backend over pre-decoded tracks; run by tests/test_inference_speed.py.

Standalone on purpose: the PyTorch backends run under another project's Python
(with torch + panns_inference), where songselector is not installed.

    python cnn14_backends.py BACKEND MODEL CHUNKS.npz OUT.npz THREADS

BACKEND: torch (eager PyTorch), torchscript (traced and frozen), onnx-noopt
(onnxruntime, graph optimisations off) or onnx (onnxruntime as the app uses it).
MODEL: the .pth checkpoint for the torch backends, the .onnx file otherwise.
Prints one JSON line: model load time and the model time of every track.
"""
import json
import sys
import time

import numpy as np


def torch_runner(backend, model_path, threads, example):
    import contextlib
    import io

    import torch
    from panns_inference import AudioTagging
    torch.set_num_threads(threads)
    torch.set_num_interop_threads(1)
    with contextlib.redirect_stdout(io.StringIO()):  # AudioTagging prints the checkpoint path
        model = AudioTagging(checkpoint_path=model_path, device='cpu').model.eval()
    if backend == 'torch':
        def run(chunk):
            with torch.inference_mode():
                return model(torch.from_numpy(chunk))['embedding'].numpy()
        return run

    class Embedding(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.inner = inner

        def forward(self, audio):
            return self.inner(audio)['embedding']

    with torch.no_grad():
        traced = torch.jit.trace(Embedding(model).eval(), torch.from_numpy(example), check_trace=False)
        compiled = torch.jit.optimize_for_inference(torch.jit.freeze(traced))

    def run(chunk):
        with torch.inference_mode():
            return compiled(torch.from_numpy(chunk)).numpy()
    return run


def onnx_runner(backend, model_path, threads):
    import onnxruntime
    options = onnxruntime.SessionOptions()  # as Cnn14Embedder._options
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
    if backend == 'onnx-noopt':
        options.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_DISABLE_ALL
    session = onnxruntime.InferenceSession(model_path, options, providers=['CPUExecutionProvider'])
    name = session.get_inputs()[0].name
    return lambda chunk: session.run(['embedding'], {name: chunk})[0]


def main(backend, model_path, chunks_path, out_path, threads):
    threads = int(threads)
    tracks = np.load(chunks_path)
    names = sorted(tracks.files)
    started = time.perf_counter()
    if backend in ('torch', 'torchscript'):
        run = torch_runner(backend, model_path, threads, tracks[names[0]][:1])
    else:
        run = onnx_runner(backend, model_path, threads)
    run(tracks[names[0]][:1])  # warm-up: first-call allocations are not model time
    load_seconds = time.perf_counter() - started
    seconds, outputs = [], {}
    for name in names:
        chunks = tracks[name]
        started = time.perf_counter()
        # One 5 s chunk per call, as the app does on the CPU (BATCH_SIZES)
        outputs[name] = np.concatenate([run(chunks[i:i + 1]) for i in range(len(chunks))])
        seconds.append(time.perf_counter() - started)
    np.savez(out_path, **outputs)
    print(json.dumps({'backend': backend, 'load_seconds': load_seconds, 'seconds': seconds}))


if __name__ == '__main__':
    main(*sys.argv[1:])

"""The GPU failing mid-run (driver reset, device removed, out of memory) moves analysis to the CPU.

Before: the session was only checked when it was created. A GPU that broke later made every remaining track fail,
and failures are remembered, so those tracks were not analysed again until their files changed.
"""
import os
import queue
import sys
import tempfile
import threading
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import soundfile
from PyQt5.QtWidgets import QApplication

from songselector.core.embedding_models import CNN14
from songselector.core.embeddings import Cancelled, EmbeddingStore, OnnxEmbedder, run_analysis
from songselector.core.traktor_collection import canonical_path
from songselector.ui.embedding_worker import EmbeddingAnalyzer

DEVICE_REMOVED = 'DXGI_ERROR_DEVICE_REMOVED'


class GpuSession:
    """Works for the first `works_for` calls, then fails like a GPU that was reset."""

    def __init__(self, works_for=0):
        self.works_for, self.calls = works_for, 0

    def run(self, outputs, feeds):
        self.calls += 1
        if self.calls > self.works_for:
            raise RuntimeError(DEVICE_REMOVED)
        return [np.ones((len(next(iter(feeds.values()))), CNN14.dim), dtype=np.float32)]


class CpuSession:
    def __init__(self, broken=False):
        self.broken, self.calls = broken, 0

    def run(self, outputs, feeds):
        self.calls += 1
        if self.broken:
            raise ValueError('the track itself is bad')
        return [np.zeros((len(next(iter(feeds.values()))), CNN14.dim), dtype=np.float32)]


def gpu_embedder(session):
    embedder = OnnxEmbedder.__new__(OnnxEmbedder)
    embedder.spec, embedder.session, embedder.input_name = CNN14, session, 'audio'
    embedder.provider, embedder.batch_size, embedder._runtime_version = 'DmlExecutionProvider', 4, 'test'
    embedder._model_path, embedder._threads, embedder.gpu_failure = 'model.onnx', 1, None
    return embedder


@contextmanager
def fake_onnxruntime(session=None):
    """A stand-in onnxruntime module whose InferenceSession returns `session`. The real package is not imported:
    onnxruntime-directml's DLL does not initialise on a CI runner without a DirectX 12 GPU."""
    create = Mock(return_value=session)
    module = types.SimpleNamespace(InferenceSession=create, SessionOptions=types.SimpleNamespace,
                                   ExecutionMode=types.SimpleNamespace(ORT_SEQUENTIAL=0))
    with patch.dict(sys.modules, {'onnxruntime': module}):
        yield create


def audio(chunks):
    return np.zeros(chunks * CNN14.chunk_samples, dtype=np.float32)


class EmbedFallbackTests(unittest.TestCase):
    def test_a_gpu_failure_redoes_the_track_on_the_cpu_and_stays_there(self):
        gpu, cpu = GpuSession(), CpuSession()
        embedder = gpu_embedder(gpu)
        with fake_onnxruntime(cpu) as create:
            first = embedder.embed(audio(3))
            second = embedder.embed(audio(2))
        self.assertEqual(first.shape, (3, CNN14.dim))
        self.assertEqual(second.shape, (2, CNN14.dim))
        self.assertEqual(create.call_args.kwargs['providers'], ['CPUExecutionProvider'])
        self.assertEqual(create.call_count, 1)  # one CPU session for the rest of the run
        self.assertEqual(gpu.calls, 1)  # the broken GPU is not tried again
        self.assertEqual(embedder.provider, 'CPUExecutionProvider')
        self.assertEqual(embedder.batch_size, 1)
        self.assertIn(DEVICE_REMOVED, embedder.gpu_failure)

    def test_a_track_the_cpu_cannot_do_either_keeps_the_gpu(self):
        gpu = GpuSession()
        embedder = gpu_embedder(gpu)
        with fake_onnxruntime(CpuSession(broken=True)):
            with self.assertRaisesRegex(ValueError, 'the track itself is bad'):
                embedder.embed(audio(2))
        self.assertIs(embedder.session, gpu)
        self.assertEqual(embedder.provider, 'DmlExecutionProvider')
        self.assertIsNone(embedder.gpu_failure)

    def test_stopping_is_not_a_gpu_failure(self):
        embedder = gpu_embedder(GpuSession(works_for=100))
        with fake_onnxruntime() as create:
            with self.assertRaises(Cancelled):
                embedder.embed(audio(2), should_stop=lambda: True)
        create.assert_not_called()
        self.assertEqual(embedder.provider, 'DmlExecutionProvider')

    def test_a_cpu_failure_is_raised_as_before(self):
        embedder = gpu_embedder(CpuSession(broken=True))
        embedder.provider, embedder.batch_size = 'CPUExecutionProvider', 1
        with fake_onnxruntime() as create:
            with self.assertRaises(ValueError):
                embedder.embed(audio(2))
        create.assert_not_called()


class AnalysisRunTests(unittest.TestCase):
    """The bug as a user would see it: a library analysis where the GPU breaks after the first track."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_tracks_after_a_gpu_failure_are_analysed_not_failed(self):
        store_path = self.root / 'embeddings.sqlite'
        tracks = []
        for number in range(4):
            path = self.root / f'{number}.wav'
            soundfile.write(str(path), np.zeros(CNN14.sample_rate * 6, dtype=np.float32), CNN14.sample_rate)
            tracks.append((canonical_path(str(path)), str(path)))
        jobs, events, stop = queue.Queue(), queue.Queue(), threading.Event()
        for job in tracks:
            jobs.put(job)
        models = [(CNN14.id, self.root / 'cnn14.onnx', store_path, lambda _path: gpu_embedder(GpuSession(1)))]
        with fake_onnxruntime(CpuSession()), \
                patch('songselector.core.embeddings._lower_process_priority'):
            thread = threading.Thread(target=run_analysis, args=(models, jobs, events, stop))
            thread.start()
            seen = []
            try:
                while sum(event[0] == 'done' for event in seen) < len(tracks):
                    seen.append(events.get(timeout=30))
            finally:
                stop.set()
                thread.join(30)
        self.assertEqual([event[2] for event in seen if event[0] == 'done'], ['analysed'] * 4)
        device = [event for event in seen if event[0] == 'device']
        self.assertEqual(len(device), 1)
        self.assertEqual(device[0][1], 'CPUExecutionProvider')
        self.assertIn(DEVICE_REMOVED, device[0][2])
        self.assertEqual(EmbeddingStore(store_path, spec=CNN14).counts(), (4, 0))


class DeviceEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_the_status_shows_the_cpu_and_warns_once(self):
        analyzer = EmbeddingAnalyzer(EmbeddingStore(self.root / 'e.sqlite'), self.root / 'm.onnx')
        analyzer.device = 'GPU (DirectML)'
        warnings = []
        analyzer.warning.connect(warnings.append)
        analyzer._handle(('device', 'CPUExecutionProvider', 'CNN14: the GPU stopped working', 1))
        analyzer._handle(('device', 'CPUExecutionProvider', 'CNN14: the GPU stopped working', 0))  # second process
        self.assertEqual(analyzer.device, 'CPU')
        self.assertEqual(warnings, ['CNN14: the GPU stopped working'])


if __name__ == '__main__':
    unittest.main()

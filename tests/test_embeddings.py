"""Embedding pipeline, storage and the background analyzer (fake model unless TKC_CNN14_ONNX is set)."""
import os
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np
import soundfile

from traktor_key_calculator.core.embeddings import (CHUNK_SAMPLES, EMBEDDING_DIM, SAMPLE_RATE, Cancelled,
                                                    Cnn14Embedder, EmbeddingStore, decode, encode,
                                                    file_fingerprint, load_audio, split_chunks)
from traktor_key_calculator.core.traktor_collection import canonical_path


def write_wav(path, seconds, sample_rate=44100, channels=2):
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    tone = 0.3 * np.sin(2 * np.pi * 440 * t)
    soundfile.write(str(path), np.stack([tone] * channels, axis=1), sample_rate)
    return path


# Test embedders run inside the analysis process, so they must be module-level classes.
class FakeEmbedder:
    """Stands in for CNN14: one row per 5 s chunk, filled with the chunk count."""

    def __init__(self, model_path):
        self.model_path = model_path

    def embed(self, audio, should_stop=lambda: False):
        count = len(split_chunks(audio))
        return np.full((count, EMBEDDING_DIM), float(count), dtype=np.float32)


class SlowEmbedder(FakeEmbedder):
    """Takes 30 s per track unless stopped."""

    def embed(self, audio, should_stop=lambda: False):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if should_stop():
                raise Cancelled()
            time.sleep(0.01)
        return super().embed(audio, should_stop)


class BriefEmbedder(FakeEmbedder):
    def embed(self, audio, should_stop=lambda: False):
        time.sleep(0.3)
        return super().embed(audio, should_stop)


class CrashingEmbedder(FakeEmbedder):
    """Kills the whole analysis process on audio shorter than 2 s, like a decoder segfault."""

    def embed(self, audio, should_stop=lambda: False):
        if len(audio) < 2 * SAMPLE_RATE:
            os._exit(3)
        return super().embed(audio, should_stop)


class BrokenModel:
    def __init__(self, model_path):
        raise RuntimeError('bad model file')


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['TRAKTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_load_audio_is_mono_32khz(self):
        audio = load_audio(write_wav(self.root / 'tone.wav', 12.5))
        self.assertEqual(audio.dtype, np.float32)
        self.assertAlmostEqual(len(audio) / SAMPLE_RATE, 12.5, places=2)

    def test_chunks_are_five_seconds_with_zero_padded_tail(self):
        chunks = split_chunks(np.ones(2 * CHUNK_SAMPLES + 10, dtype=np.float32))
        self.assertEqual(chunks.shape, (3, CHUNK_SAMPLES))
        self.assertEqual(chunks[2, :10].sum(), 10)
        self.assertEqual(chunks[2, 10:].sum(), 0)
        self.assertEqual(split_chunks(np.zeros(0, dtype=np.float32)).shape, (1, CHUNK_SAMPLES))

    def test_encoding_is_lossless_for_float16_and_compresses_sparse_data(self):
        matrix = np.zeros((60, EMBEDDING_DIM), dtype=np.float32)
        matrix[:, ::8] = np.random.default_rng(1).random((60, EMBEDDING_DIM // 8))
        blob = encode(matrix)
        self.assertTrue(np.array_equal(decode(blob, 60), matrix.astype(np.float16)))
        self.assertLess(len(blob), matrix.astype(np.float16).nbytes / 3)

    def test_gpu_batches_have_a_fixed_shape_and_padding_is_removed(self):
        class StubSession:
            shapes = []

            def run(self, _outputs, feeds):
                batch = feeds['audio']
                StubSession.shapes.append(batch.shape)
                return [np.repeat(batch[:, :1], EMBEDDING_DIM, axis=1)]  # row value = first sample

        embedder = Cnn14Embedder.__new__(Cnn14Embedder)
        embedder.session, embedder.input_name, embedder.batch_size = StubSession(), 'audio', 8
        audio = np.zeros(10 * CHUNK_SAMPLES, dtype=np.float32)
        audio[::CHUNK_SAMPLES] = np.arange(1, 11)  # first sample of chunk i is i + 1
        matrix = embedder.embed(audio)
        self.assertEqual(matrix.shape, (10, EMBEDDING_DIM))
        self.assertEqual(list(matrix[:, 0]), list(range(1, 11)))
        self.assertEqual(StubSession.shapes, [(8, CHUNK_SAMPLES), (8, CHUNK_SAMPLES)])

    @unittest.skipUnless(os.name == 'nt', 'Windows priority classes')
    def test_analysis_process_has_below_normal_cpu_and_very_low_io_priority(self):
        import subprocess, sys
        code = ('import ctypes; from ctypes import wintypes; '
                'from traktor_key_calculator.core.embeddings import _lower_process_priority; '
                '_lower_process_priority(); k = ctypes.WinDLL("kernel32"); '
                'k.GetCurrentProcess.restype = wintypes.HANDLE; k.GetPriorityClass.argtypes = (wintypes.HANDLE,); '
                'io = ctypes.c_ulong(); ctypes.WinDLL("ntdll").NtQueryInformationProcess('
                'wintypes.HANDLE(-1), 33, ctypes.byref(io), 4, None); '  # 33 = ProcessIoPriority
                'print(k.GetPriorityClass(k.GetCurrentProcess()), io.value)')
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1] / 'src'))
        result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.stdout.split(), [str(0x4000), '0'], result.stderr)  # below normal, very low I/O

    def test_store_results_errors_and_fingerprints(self):
        store = EmbeddingStore(self.root / 'embeddings.sqlite')
        store.save('a', (1, 2), np.ones((3, EMBEDDING_DIM)))
        store.save_error('b', (5, 6), ValueError('cannot decode'))
        self.assertEqual(store.load('a').shape, (3, EMBEDDING_DIM))
        self.assertIsNone(store.load('b'))
        self.assertEqual(store.fingerprints(), {'a': (1, 2), 'b': (5, 6)})
        self.assertEqual(store.counts(), (1, 1))
        store.update_fingerprint('a', (7, 8))
        self.assertEqual(store.fingerprints()['a'], (7, 8))
        self.assertEqual(store.fingerprints(model='other-model'), {})


class AnalyzerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['TRAKTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)
        self.store = EmbeddingStore(self.root / 'embeddings.sqlite')
        self.analyzers = []

    def tearDown(self):
        for analyzer in self.analyzers:
            analyzer.stop()
        self.temp.cleanup()

    def analyzer(self, factory=FakeEmbedder):
        from traktor_key_calculator.ui.embedding_worker import EmbeddingAnalyzer
        analyzer = EmbeddingAnalyzer(self.store, self.root / 'model.onnx', factory)
        analyzer.analysed = []
        analyzer.track_analyzed.connect(analyzer.analysed.append)
        self.analyzers.append(analyzer)
        return analyzer

    def run_analyzer(self, tracks, factory=FakeEmbedder):
        analyzer = self.analyzer(factory)
        progress = []
        analyzer.progress.connect(lambda *values: progress.append(values))
        analyzer.submit((canonical_path(path), str(path)) for path in tracks)
        analyzer.start()
        self.assertTrue(analyzer.wait_idle(60))
        analyzer.stop()
        return analyzer, progress

    def test_analyses_new_files_records_errors_and_skips_missing(self):
        good = [write_wav(self.root / f'{n}.wav', seconds) for n, seconds in (('a', 6), ('b', 11))]
        broken = self.root / 'broken.mp3'
        broken.write_bytes(b'not audio')
        analyzer, progress = self.run_analyzer(good + [broken, self.root / 'missing.mp3'])
        self.assertEqual(self.store.load(canonical_path(good[0])).shape, (2, EMBEDDING_DIM))
        self.assertEqual(self.store.load(canonical_path(good[1])).shape, (3, EMBEDDING_DIM))
        self.assertEqual(self.store.counts(), (2, 1))
        self.assertEqual(len(analyzer.analysed), 2)
        self.assertEqual(progress[-1], (4, 4, 1, ''))

    def test_current_embeddings_are_skipped_and_changed_files_reanalysed(self):
        tracks = [write_wav(self.root / f'{n}.wav', 3) for n in 'ab']
        self.assertEqual(len(self.run_analyzer(tracks)[0].analysed), 2)
        self.assertEqual(len(self.run_analyzer(tracks)[0].analysed), 0)
        write_wav(tracks[0], 7)
        os.utime(tracks[0], ns=(time.time_ns(), time.time_ns() + 10**9))
        self.assertEqual(self.run_analyzer(tracks)[0].analysed, [canonical_path(tracks[0])])
        self.assertEqual(self.store.load(canonical_path(tracks[0])).shape, (2, EMBEDDING_DIM))

    def test_stop_interrupts_a_track_and_the_next_start_finishes_it(self):
        track = write_wav(self.root / 'long.wav', 4)
        analyzer = self.analyzer(SlowEmbedder)
        analyzer.submit([(canonical_path(track), str(track))])
        analyzer.start()
        deadline = time.monotonic() + 30
        while analyzer._current is None and time.monotonic() < deadline:
            analyzer._poll()
            time.sleep(0.05)
        self.assertIsNotNone(analyzer._current, 'analysis never started')
        analyzer.stop()
        self.assertFalse(analyzer.running)
        self.assertIsNone(self.store.load(canonical_path(track)))
        analyzer.embedder_factory = FakeEmbedder
        analyzer.start()
        self.assertTrue(analyzer.wait_idle(60))
        self.assertIsNotNone(self.store.load(canonical_path(track)))

    def test_app_can_exit_after_stopping_with_a_large_backlog(self):
        # Regression: queuing thousands of jobs at once filled the pipe and the
        # queue's feeder thread then kept the app from exiting.
        import subprocess, sys
        script = '\n'.join([
            'import sys, time',
            'from pathlib import Path',
            'from PyQt5.QtWidgets import QApplication',
            'from traktor_key_calculator.core.embeddings import EmbeddingStore',
            'from traktor_key_calculator.ui.embedding_worker import EmbeddingAnalyzer',
            'from test_embeddings import SlowEmbedder, write_wav',
            'if __name__ == "__main__":',
            '    app = QApplication([])',
            '    root = Path(sys.argv[1])',
            '    track = write_wav(root / "slow.wav", 2)',
            '    analyzer = EmbeddingAnalyzer(EmbeddingStore(root / "e.sqlite"), root / "m.onnx", SlowEmbedder)',
            '    analyzer.submit([("slow", str(track))] + [(f"k{i}", "E:/nowhere/" + "x" * 80 + f"{i}.mp3") for i in range(3000)])',
            '    analyzer.start()',
            '    time.sleep(3)',
            '    analyzer.stop()',
        ])
        script_path = self.root / 'exit_check.py'
        script_path.write_text(script)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(Path(__file__).parents[1] / 'src'),
                                                           str(Path(__file__).parent)]))
        result = subprocess.run([sys.executable, str(script_path), str(self.root)], env=env,
                                timeout=90, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_a_crash_on_one_file_is_recorded_and_analysis_continues(self):
        crash = write_wav(self.root / 'crash.wav', 1)
        fine = write_wav(self.root / 'fine.wav', 3)
        analyzer, _ = self.run_analyzer([crash, fine], CrashingEmbedder)
        self.assertEqual(analyzer.analysed, [canonical_path(fine)])
        self.assertEqual(self.store.counts(), (1, 1))

    def test_model_load_failure_is_reported_not_raised(self):
        analyzer = self.analyzer(BrokenModel)
        messages = []
        analyzer.failed.connect(messages.append)
        analyzer.submit([('x', str(self.root / 'x.wav'))])
        analyzer.start()
        self.assertFalse(analyzer.wait_idle(60))
        self.assertIn('bad model file', messages[0])
        self.assertFalse(analyzer.running)


class WindowAnalysisTests(unittest.TestCase):
    """The window starts analysis in the background and stays responsive."""

    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application = QApplication.instance() or QApplication([])

    def test_window_analyses_library_tracks_without_blocking(self):
        import copy, json
        from unittest.mock import patch
        import pandas as pd
        from PyQt5.QtCore import QTimer
        from traktor_key_calculator.config import SETTINGS_DEFAULT
        from traktor_key_calculator.ui.embedding_worker import EmbeddingAnalyzer

        with tempfile.TemporaryDirectory(dir=os.environ['TRAKTOR_APP_DATA_DIR']) as folder:
            root = Path(folder)
            model = root / 'models' / 'cnn14.onnx'
            model.parent.mkdir()
            model.write_bytes(b'fake')
            tracks = [write_wav(root / f'{n}.wav', 2) for n in 'abc']
            settings = copy.deepcopy(SETTINGS_DEFAULT)
            settings['Traktor collection'] = ''
            (root / 'settings.json').write_text(json.dumps(settings))
            library = pd.DataFrame([{'Artist': 'T', 'Title': p.stem, 'BPM': 120, 'File_Path': str(p),
                                     'Musical_Key_Base': 'C', 'BaseMinorOrMajor': 'major'} for p in tracks])
            with patch('traktor_key_calculator.ui.main_window.SETTINGS_FILE', str(root / 'settings.json')), \
                    patch('traktor_key_calculator.ui.main_window.DataManager.load_default_data', return_value=library), \
                    patch('traktor_key_calculator.ui.main_window.EmbeddingAnalyzer',
                          lambda store, path, parent=None: EmbeddingAnalyzer(store, path, BriefEmbedder, parent)):
                from traktor_key_calculator.ui.main_window import TraktorKeyCalculator
                window = TraktorKeyCalculator()
                self.assertTrue(window.embedding_analyzer.running)
                ticks = []
                timer = QTimer()
                timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
                timer.start(20)
                deadline = time.perf_counter() + 0.5
                while time.perf_counter() < deadline:
                    self.application.processEvents()
                # The event loop kept running (timer fired) while analysis was busy.
                self.assertGreater(len(ticks), 10)
                self.assertTrue(window.embedding_analyzer.wait_idle(60))
                timer.stop()
                self.assertIn('3/3', window.embedding_label.text())
                self.assertIn('up to date', window.embedding_label.text())
                self.assertEqual(window.embedding_store.counts(), (3, 0))
                window.close()
                self.assertFalse(window.embedding_analyzer.running)


@unittest.skipUnless(os.environ.get('TKC_CNN14_ONNX'), 'set TKC_CNN14_ONNX to the cnn14.onnx path to run')
class RealModelTests(unittest.TestCase):
    """Runs the real CNN14 through the analysis process, exactly as the app does."""

    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application = QApplication.instance() or QApplication([])

    def test_real_cnn14_produces_2048_values_per_5_seconds(self):
        from traktor_key_calculator.ui.embedding_worker import EmbeddingAnalyzer
        with tempfile.TemporaryDirectory(dir=os.environ['TRAKTOR_APP_DATA_DIR']) as folder:
            track = write_wav(Path(folder) / 'tone.wav', 11)
            store = EmbeddingStore(Path(folder) / 'embeddings.sqlite')
            analyzer = EmbeddingAnalyzer(store, os.environ['TKC_CNN14_ONNX'])
            analyzer.submit([(canonical_path(track), str(track))])
            analyzer.start()
            try:
                self.assertTrue(analyzer.wait_idle(120))
            finally:
                analyzer.stop()
            matrix = store.load(canonical_path(track))
            self.assertEqual(matrix.shape, (3, EMBEDDING_DIM))
            self.assertTrue(np.isfinite(matrix).all())
            self.assertGreater(np.mean(matrix == 0), 0.3)  # ReLU output is mostly zeros

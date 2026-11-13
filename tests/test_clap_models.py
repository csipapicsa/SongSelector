"""Several embedding models (CNN14 + CLAP) and free-text search, without the real model files.

The real models are large and not in the repo; scripts/export_clap_onnx.py checks them against PyTorch when they
are made. Here: the model definitions, decoding for several sample rates, one analysis process feeding several
caches, tokenising, ranking, the text search process and the search window, all with stand-ins.
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication

from songselector.core.embedding_models import CNN14, LAION_CLAP, MODELS, MS_CLAP, model, store_path
from songselector.core.embeddings import EmbeddingStore, load_audio, load_audio_rates
from songselector.core.text_search import clap_track_vector, rank, tokenize, unit
from songselector.core.traktor_collection import canonical_path
from songselector.ui.embedding_worker import EmbeddingAnalyzer
from songselector.ui.text_search_worker import TextSearchWorker


def write_wav(path, seconds, rate=44100):
    t = np.arange(int(seconds * rate)) / rate
    soundfile.write(str(path), (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), rate)
    return path


# Stand-ins run inside spawned processes, so they are module-level classes.
class FakeCnn14:
    def __init__(self, model_path):
        pass

    def embed(self, audio, should_stop=lambda: False):
        return np.full((2, CNN14.dim), len(audio) / 1000, dtype=np.float32)  # how much audio it got (float16-safe)


class FakeLaion(FakeCnn14):
    def embed(self, audio, should_stop=lambda: False):
        return np.full((2, LAION_CLAP.dim), len(audio) / 1000, dtype=np.float32)


class FakeTextEncoder:
    """'dnb' points along the first axis, anything else along the second."""

    def __init__(self, spec, folder):
        self.dim = spec.dim

    def encode(self, text):
        vector = np.zeros(self.dim, dtype=np.float32)
        vector[0 if 'dnb' in text else 1] = 1
        return vector


class ModelDefinitionTests(unittest.TestCase):
    def test_models_and_their_files(self):
        self.assertEqual(list(MODELS), [CNN14.id, LAION_CLAP.id, MS_CLAP.id])
        self.assertEqual((LAION_CLAP.chunk_samples, MS_CLAP.chunk_samples, CNN14.chunk_samples), (480000, 308700, 160000))
        self.assertFalse(CNN14.has_text)
        self.assertTrue(LAION_CLAP.has_text and MS_CLAP.has_text)
        self.assertIs(model('unknown, e.g. from a newer version'), CNN14)
        self.assertEqual(store_path('D:/data', CNN14).name, 'embeddings.sqlite')  # the cache of earlier versions
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(LAION_CLAP.missing_files(folder), LAION_CLAP.files())
            for name in LAION_CLAP.files():
                Path(folder, name).write_bytes(b'x')
            self.assertEqual(LAION_CLAP.missing_files(folder), [])


class DecodingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_one_decode_for_every_rate_and_cnn14_unchanged(self):
        path = write_wav(self.root / 'tone.wav', 3)
        audio = load_audio_rates(path, [32000, 48000, 44100])
        self.assertEqual(sorted(audio), [32000, 44100, 48000])
        for rate, samples in audio.items():
            self.assertAlmostEqual(len(samples) / rate, 3, places=2)
        np.testing.assert_array_equal(audio[32000], load_audio(path))  # CNN14's input exactly as before
        np.testing.assert_array_equal(audio[44100], soundfile.read(str(path), dtype='float32')[0])  # native: untouched

    def test_each_model_has_its_own_cache_and_metadata(self):
        store = EmbeddingStore(self.root / 'laion.sqlite', spec=LAION_CLAP)
        store.save('a', (1, 2), np.ones((3, 512), dtype=np.float32))
        self.assertEqual(store.load('a').shape, (3, 512))
        self.assertEqual(store.fingerprints(), {'a': (1, 2)})
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.root / 'laion.sqlite')) as connection:
            row = connection.execute('SELECT model, sample_rate, chunk_seconds, dim FROM embeddings').fetchone()
        self.assertEqual(row, (LAION_CLAP.id, 48000, 10, 512))
        self.assertEqual(EmbeddingStore(self.root / 'cnn14.sqlite').spec, CNN14)  # the default, as before


class MultiModelAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_one_process_fills_every_model_cache_at_its_own_rate(self):
        cnn14 = EmbeddingStore(self.root / 'embeddings.sqlite')
        laion = EmbeddingStore(self.root / 'embeddings-laion-clap.sqlite', spec=LAION_CLAP)
        tracks = [(canonical_path(str(path)), str(path)) for path in
                  (write_wav(self.root / 'a.wav', 3), write_wav(self.root / 'b.wav', 2))]
        analyzer = EmbeddingAnalyzer(cnn14, self.root / 'cnn14.onnx', FakeCnn14,
                                     extra_models=[(laion, self.root / 'laion.onnx', FakeLaion)])
        analyzer.submit(tracks)
        analyzer.start()
        try:
            self.assertTrue(analyzer.wait_idle(60))
        finally:
            analyzer.stop()
        key = tracks[0][0]
        self.assertEqual(float(cnn14.load(key)[0, 0]), 3 * 32)   # CNN14 got 32 kHz audio
        self.assertEqual(float(laion.load(key)[0, 0]), 3 * 48)   # LAION got 48 kHz audio of the same file
        self.assertEqual(len(laion.fingerprints()), 2)

        # Switching a model on later: only that model's missing tracks are analysed.
        ms = EmbeddingStore(self.root / 'embeddings-ms-clap.sqlite', spec=MS_CLAP)
        self.assertEqual(analyzer.configuration[1][0], LAION_CLAP.id)
        again = EmbeddingAnalyzer(cnn14, self.root / 'cnn14.onnx', FakeCnn14,
                                  extra_models=[(laion, self.root / 'laion.onnx', FakeLaion),
                                                (ms, self.root / 'ms.onnx', FakeMs)])
        messages = []
        again.failed.connect(messages.append)
        again.warning.connect(messages.append)
        again.submit(tracks)
        again.start()
        try:
            self.assertTrue(again.wait_idle(60), messages)
        finally:
            again.stop()
        self.assertAlmostEqual(float(ms.load(key)[0, 0]), 3 * 44.1, delta=0.2)  # float16 storage


class FakeMs(FakeCnn14):
    def embed(self, audio, should_stop=lambda: False):
        return np.full((2, MS_CLAP.dim), len(audio) / 1000, dtype=np.float32)


class TextSearchTests(unittest.TestCase):
    def tokenizer(self):
        from tokenizers import Tokenizer, models, pre_tokenizers
        vocabulary = {'!': 0, '[UNK]': 1, 'funky': 2, 'breakbeat': 3, '<|endoftext|>': 4}
        tokenizer = Tokenizer(models.WordLevel(vocabulary, unk_token='[UNK]'))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        tokenizer.add_special_tokens(['<|endoftext|>'])
        return tokenizer

    def test_tokenize_with_and_without_fixed_length(self):
        ids, mask = tokenize(self.tokenizer(), 'funky breakbeat')
        self.assertEqual((ids.tolist(), mask.tolist(), ids.dtype), ([[2, 3]], [[1, 1]], np.int64))
        ids, mask = tokenize(self.tokenizer(), 'funky breakbeat', pad_to=5, suffix=' <|endoftext|>')
        self.assertEqual((ids.tolist(), mask.tolist()), ([[2, 3, 4, 0, 0]], [[1, 1, 1, 0, 0]]))  # as Microsoft CLAP
        ids, mask = tokenize(self.tokenizer(), 'funky ' * 10, pad_to=4)
        self.assertEqual(ids.shape, (1, 4))

    def test_track_vector_and_ranking(self):
        windows = np.array([[3, 0], [0, 1]], dtype=np.float32)  # loud first window must not dominate
        np.testing.assert_allclose(clap_track_vector(windows), unit([1, 1]), atol=1e-6)
        vectors = unit(np.array([[1, 0], [0.7, 0.7], [0, 1]], dtype=np.float32))
        self.assertEqual([key for key, _ in rank(np.array([1, 0.1]), ['a', 'b', 'c'], vectors)], ['a', 'b', 'c'])
        self.assertEqual(len(rank(np.array([1, 0]), ['a', 'b', 'c'], vectors, top=2)), 2)
        self.assertEqual(rank(np.array([1, 0]), [], vectors[:0]), [])

    def test_text_process_answers_queries(self):
        application = QApplication.instance() or QApplication([])
        worker = TextSearchWorker('unused', FakeTextEncoder)
        answers = {}
        worker.vector_ready.connect(lambda request, vector: answers.update({request: vector}))
        try:
            first, second = worker.query(LAION_CLAP.id, 'dark dnb'), worker.query(LAION_CLAP.id, 'calm')
            deadline = time.monotonic() + 60
            while len(answers) < 2 and time.monotonic() < deadline:
                application.processEvents()
                time.sleep(0.02)
        finally:
            worker.stop()
        self.assertEqual(int(np.argmax(answers[first])), 0)
        self.assertEqual(int(np.argmax(answers[second])), 1)


class FakeWorker(QObject):
    """The search window's text process, answered at once with FakeTextEncoder's vectors."""
    vector_ready = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)

    def __init__(self):
        super().__init__()
        self.queries = []

    def query(self, model_id, text):
        self.queries.append((model_id, text))
        request = len(self.queries)
        vector = FakeTextEncoder(MODELS[model_id], '').encode(text)
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, lambda: self.vector_ready.emit(request, vector))
        return request

    def stop(self, timeout=0):
        pass


class SearchWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def wait(self, condition, timeout=20):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.assertTrue(condition())

    def test_prompt_lists_the_closest_library_tracks_and_prompts_are_saved(self):
        from songselector.ui.text_search_dialog import TextSearchDialog
        store = EmbeddingStore(self.root / 'laion.sqlite', spec=LAION_CLAP)
        for index in range(6):  # tracks 0-2 lean towards 'dnb' (axis 0), 3-5 towards axis 1
            windows = np.zeros((3, 512), dtype=np.float32)
            windows[:, 0 if index < 3 else 1] = 1
            windows[:, 2] = index / 10
            store.save(f'k{index}', (1, 1), windows)
        library = {f'k{index}': {'Artist': f'Artist {index}', 'Title': f'Title {index}', 'Path': f'C:/t{index}.mp3',
                                 'Original BPM': '174'} for index in range(5)}  # k5: analysed, no longer in the library
        settings, selected, added = {}, [], []
        worker = FakeWorker()
        dialog = TextSearchDialog([LAION_CLAP], {LAION_CLAP.id: store}, self.root, settings, library.get,
                                  selected.append, added.extend, worker=worker)
        try:
            self.wait(lambda: LAION_CLAP.id in dialog._vectors)
            dialog.count.setValue(5)
            dialog.prompt.setText('rolling dnb')
            dialog.search()
            self.wait(lambda: dialog.results.topLevelItemCount() == 5)
            titles = [dialog.results.topLevelItem(i).text(3) for i in range(5)]
            self.assertEqual(set(titles[:3]), {'Title 0', 'Title 1', 'Title 2'})
            self.assertNotIn('Title 5', titles)
            self.assertEqual(worker.queries, [(LAION_CLAP.id, 'rolling dnb')])

            dialog.save_prompt()
            self.assertEqual(settings['Saved prompts'], ['rolling dnb'])
            dialog.results.topLevelItem(0).setSelected(True)
            dialog._add_selected()
            self.assertEqual(len(added), 1)
            urls = dialog.results.mimeData([dialog.results.topLevelItem(0)]).urls()
            self.assertTrue(urls[0].toLocalFile().endswith('.mp3'))  # drag onto Traktor gives the file
        finally:
            dialog.close()


class MainWindowModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        import copy

        import pandas as pd

        from songselector.config import SETTINGS_DEFAULT
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)
        settings = copy.deepcopy(SETTINGS_DEFAULT)
        settings.update({'Traktor collection': '', 'Advanced search': {'enabled': False, 'filters': []}})
        (self.root / 'settings.json').write_text(json.dumps(settings))
        library = pd.DataFrame([{'Artist': 'A', 'Title': 'T', 'BPM': 128, 'File_Path': str(self.root / 'a.mp3'),
                                 'Musical_Key_Base': 'A', 'BaseMinorOrMajor': 'minor'}])
        self.patches = [patch('songselector.ui.main_window.SETTINGS_FILE', str(self.root / 'settings.json')),
                        patch('songselector.ui.main_window.DataManager.load_default_data',
                              side_effect=lambda: library.copy())]
        for active in self.patches:
            active.start()
        from songselector.ui.main_window import MainWindow
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()
        self.application.processEvents()
        for active in self.patches:
            active.stop()
        self.temp.cleanup()

    def test_models_without_files_cannot_be_switched_on_and_the_map_follows_the_chosen_model(self):
        window = self.window
        self.assertEqual(set(window.model_stores), set(MODELS))
        self.assertEqual(window.model_stores[LAION_CLAP.id].path.name, 'embeddings-laion-clap.sqlite')
        window._update_model_menu()
        action = window.model_actions[LAION_CLAP.id]
        self.assertFalse(action.isEnabled())
        self.assertIn('missing', action.text())
        self.assertEqual(window.searchable_models(), [])

        models = self.root / 'models'
        models.mkdir()
        for name in LAION_CLAP.files():
            (models / name).write_bytes(b'x')
        window._update_model_menu()
        self.assertTrue(action.isEnabled())
        self.assertEqual(window.searchable_models(), [LAION_CLAP])

        window.set_similarity_model(LAION_CLAP.id)
        self.assertIs(window.similarity_map.store, window.model_stores[LAION_CLAP.id])
        self.assertEqual(window.settings['Similarity model'], LAION_CLAP.id)



@unittest.skipUnless(os.environ.get('SONGSELECTOR_CLAP_MODELS'), 'set SONGSELECTOR_CLAP_MODELS to the folder with '
                     'the clap-*.onnx files (scripts/export_clap_onnx.py) to run')
class RealClapModelTests(unittest.TestCase):
    """The exported models through the app's own code: audio windows, text vectors, and that they meet."""

    def test_audio_and_text_through_the_app(self):
        from songselector.core.embeddings import OnnxEmbedder
        from songselector.core.text_search import TextEncoder
        folder = Path(os.environ['SONGSELECTOR_CLAP_MODELS'])
        for spec in (LAION_CLAP, MS_CLAP):
            with self.subTest(spec.name):
                embedder = OnnxEmbedder(folder / spec.audio_file, model_id=spec.id)
                rate = spec.sample_rate
                t = np.arange(int(rate * spec.chunk_seconds * 1.5)) / rate
                windows = embedder.embed((0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32))
                self.assertEqual(windows.shape, (2, spec.dim))  # 1.5 windows -> 2, the last zero-padded
                encoder = TextEncoder(spec, folder)
                tone, speech = encoder.encode('a pure sine tone'), encoder.encode('a man giving a speech')
                self.assertAlmostEqual(float(np.linalg.norm(tone)), 1, places=4)
                track = clap_track_vector(windows[:1])
                self.assertGreater(float(track @ tone), float(track @ speech))  # the text side understands the audio

if __name__ == '__main__':
    unittest.main(verbosity=2)

"""Several embedding models (CNN14 + CLAP) and free-text search, without the real model files.

The real models are large and not in the repo; scripts/export_clap_onnx.py checks them against PyTorch when they
are made. Here: the model definitions, decoding for several sample rates, one analysis process feeding several
caches, tokenising, ranking, the text search process and the search window, all with stand-ins.
"""
import hashlib
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
from PyQt5.QtWidgets import QApplication, QLabel

from songselector.core import model_download
from songselector.core.embedding_models import AMC_CLAP, CNN14, LAION_CLAP, MODELS, MS_CLAP, model, store_path
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
        self.assertEqual(list(MODELS), [CNN14.id, LAION_CLAP.id, MS_CLAP.id, AMC_CLAP.id])
        self.assertEqual((AMC_CLAP.chunk_samples, AMC_CLAP.dim), (240000, 512))
        self.assertTrue(AMC_CLAP.has_text)
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


# The tests stand in a one-byte file b'x' for each model file; the app checks a model file's size and SHA-256
# (core/model_download.py), so here those are the stand-in's.
STAND_IN_FILES = {name: (1, hashlib.sha256(b'x').hexdigest()) for name in model_download.FILES}


class WindowCase(unittest.TestCase):
    """A main window on a one-track library with grouping on."""

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
        settings.update({'Traktor collection': '', 'Advanced search': {'enabled': False, 'filters': []},
                         'Map grouping': 'communities'})
        (self.root / 'settings.json').write_text(json.dumps(settings))
        library = pd.DataFrame([{'Artist': 'A', 'Title': 'T', 'BPM': 128, 'File_Path': str(self.root / 'a.mp3'),
                                 'Musical_Key_Base': 'A', 'BaseMinorOrMajor': 'minor'}])
        self.patches = [patch('songselector.ui.main_window.SETTINGS_FILE', str(self.root / 'settings.json')),
                        patch('songselector.ui.main_window.DataManager.load_default_data',
                              side_effect=lambda: library.copy()),
                        patch.dict('songselector.core.model_download.FILES', STAND_IN_FILES)]
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


class MainWindowModelTests(WindowCase):
    def test_groups_wait_until_the_similarity_model_has_analysed_the_library(self):
        # Grouping is on and the Group column is shown, but no track is analysed yet: nothing to group.
        self.assertTrue(self.window._groups_waiting)
        self.assertIn('Groups wait', self.window.status_label.text())
        self.assertIsNone(self.window.similarity_map.data)  # no map loaded for nothing

    def test_model_files_are_checked_once_in_the_background_and_a_damaged_model_is_switched_off(self):
        # Asked 2026-11-21: a proper check of the model files at start, not just "a file of that name is there".
        window = self.window
        models = self.root / 'models'
        models.mkdir()
        for name in LAION_CLAP.files():
            (models / name).write_bytes(b'x')  # copied in by hand: right size, checksum not computed yet

        def check():
            window.check_model_files()
            deadline = time.monotonic() + 20
            while window._model_check_thread is not None and time.monotonic() < deadline:
                self.application.processEvents()
                time.sleep(0.01)

        with patch.object(window, 'start_embedding_analysis'):  # the stand-in files are not real models
            self.assertEqual(model_download.model_state(window.model_file_states(LAION_CLAP)), model_download.CHECKING)
            self.assertIsNotNone(window.model_file(LAION_CLAP))  # usable while it is being checked
            check()
            self.assertEqual(model_download.model_state(window.model_file_states(LAION_CLAP)), model_download.INSTALLED)
            self.assertTrue(all(window.settings['Model file checks'][str(models / name)][2]
                                for name in LAION_CLAP.files()))  # remembered: not computed again at the next start
            damaged = models / LAION_CLAP.text_file
            damaged.write_bytes(b'y')  # same size, other bytes
            stat = damaged.stat()
            os.utime(damaged, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
            check()
        self.assertIsNone(window.model_file(LAION_CLAP))
        self.assertIn('damaged', window.model_actions[LAION_CLAP.id].text())
        self.assertIn('Damaged model files', window.status_label.text())
        self.assertIn(f'{LAION_CLAP.text_file}: wrong checksum', window.status_label.text())

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

        with patch.object(window, 'start_embedding_analysis'):  # the stand-in files are not real models
            window.set_similarity_model(LAION_CLAP.id)
        self.assertIs(window.similarity_map.store, window.model_stores[LAION_CLAP.id])
        self.assertEqual(window.settings['Similarity model'], LAION_CLAP.id)

    def test_one_model_box_drives_the_map_and_the_description_search(self):
        # Asked 2026-11-20: the model is chosen next to "Describe a sound" and the similarity map follows it (the map's
        # own Model box is gone). CNN14 is listed too; it has no text side, so the description field then says so.
        from songselector.ui.main_window import DESCRIPTION_HINT
        window = self.window
        models = self.root / 'models'
        models.mkdir()
        for name in LAION_CLAP.files():
            (models / name).write_bytes(b'x')
        window._refresh_model_box()  # as after a download
        box = window.model_box
        self.assertEqual(box.currentData(), CNN14.id)  # the similarity model, as before
        self.assertNotEqual(box.findData(LAION_CLAP.id), -1)
        self.assertEqual(box.findData(MS_CLAP.id), -1)  # no files: not offered
        self.assertFalse(window.description_box.isEnabled())
        self.assertIn('CNN14 cannot search by description', window.description_box.lineEdit().placeholderText())

        with patch.object(window, 'start_embedding_analysis'):  # the stand-in files are not real models
            box.activated.emit(box.findData(LAION_CLAP.id))
        self.assertIs(window.similarity_map.store, window.model_stores[LAION_CLAP.id])
        self.assertEqual(window.settings['Similarity model'], LAION_CLAP.id)
        self.assertEqual(window.settings['Text search model'], LAION_CLAP.id)
        self.assertTrue(window.description_box.isEnabled())
        self.assertEqual(window.description_box.lineEdit().placeholderText(), DESCRIPTION_HINT)

        with patch.object(window, 'start_embedding_analysis'):
            window.set_similarity_model(CNN14.id)  # Analysis -> Similarity model: the box follows
        self.assertEqual(box.currentData(), CNN14.id)
        self.assertEqual(window.settings['Text search model'], LAION_CLAP.id)  # the last CLAP model is kept

    def test_a_chosen_models_folder_is_where_the_models_are_looked_for(self):
        # Asked 2026-11-20 (Get models -> Models folder..., also in the Analysis menu).
        window = self.window
        shared = self.root / 'shared models'
        shared.mkdir()
        for name in LAION_CLAP.files():
            (shared / name).write_bytes(b'x')
        self.assertEqual(window.searchable_models(), [])
        with patch.object(window, 'start_embedding_analysis'):  # the stand-in files are not real models
            window.set_models_folder(shared)
        self.assertEqual(window.settings['Models folder'], str(shared))
        self.assertEqual(window.models_folder(), shared)
        self.assertEqual(window.searchable_models(), [LAION_CLAP])
        self.assertNotEqual(window.model_box.findData(LAION_CLAP.id), -1)
        self.assertIn('LAION CLAP', window.status_label.text())
        with patch.object(window, 'start_embedding_analysis'):
            window.set_models_folder(window.default_models_folder())  # back to the default: not stored as a path
        self.assertEqual(window.settings['Models folder'], '')
        self.assertEqual(window.searchable_models(), [])

    def test_store_coverage_counts_analysed_and_failed_tracks(self):
        store = EmbeddingStore(self.root / 'coverage.sqlite', spec=LAION_CLAP)
        store.save('a', (1, 1), np.zeros((2, LAION_CLAP.dim), dtype=np.float32))
        store.save_error('b', (1, 1), 'broken')
        self.assertEqual(store.keys(), ({'a'}, {'b'}))

    def test_choosing_a_model_that_misses_tracks_switches_it_on_and_analyses_them(self):
        window = self.window
        models = self.root / 'models'
        models.mkdir()
        for name in LAION_CLAP.files():
            (models / name).write_bytes(b'x')
        key = canonical_path(str(self.root / 'a.mp3'))
        self.assertEqual(window.model_coverage(LAION_CLAP.id), (0, 0, 1))
        self.assertNotIn(LAION_CLAP.id, window.enabled_model_ids())

        with patch.object(window, 'start_embedding_analysis') as start:
            window.set_similarity_model(LAION_CLAP.id)
        start.assert_called()
        self.assertIn(LAION_CLAP.id, window.enabled_model_ids())  # switched on for its missing track
        self.assertIn('LAION CLAP has analysed 0 of 1 tracks', window.status_label.text())
        self.assertIn('analysing the other 1', window.status_label.text())
        self.assertIn('LAION CLAP: 0 of 1 tracks analysed', window.embedding_label.toolTip())

        # Once the model has the library, choosing it again starts nothing.
        window.model_stores[LAION_CLAP.id].save(key, (1, 1), np.zeros((1, LAION_CLAP.dim), dtype=np.float32))
        self.assertEqual(window.model_coverage(LAION_CLAP.id), (1, 0, 1))
        with patch.object(window, 'start_embedding_analysis') as start:
            self.assertEqual(window.ensure_models_analysed([LAION_CLAP.id]), [])
        start.assert_not_called()
        window._update_model_menu()
        self.assertIn('1 of 1 tracks', window.similarity_actions[LAION_CLAP.id].text())

    def test_a_paused_analysis_is_not_started_but_says_so(self):
        window = self.window
        models = self.root / 'models'
        models.mkdir()
        for name in MS_CLAP.files():
            (models / name).write_bytes(b'x')
        window.settings['Embedding analysis'] = False
        with patch.object(window, 'start_embedding_analysis'):
            messages = window.ensure_models_analysed([MS_CLAP.id])
        self.assertIn('paused', messages[0])


class StatusLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_a_long_message_does_not_widen_the_window(self):
        from songselector.ui.elided_label import MIN_WIDTH, ElidedLabel
        label = ElidedLabel('short')
        label.setText('a very long status message about a file ' * 20)
        self.assertEqual(label.minimumSizeHint().width(), MIN_WIDTH)
        self.assertTrue(label.text().startswith('a very long'))  # the whole text, not the elided one
        self.assertIn('a very long', label.toolTip())
        label.resize(120, 20)
        label.show()  # a hidden widget gets its resize event only when shown
        self.assertLess(label.fontMetrics().horizontalAdvance(QLabel.text(label)), 130)
        label.close()
        label.set_details('CNN14: 1 of 1 tracks analysed')
        self.assertIn('CNN14', label.toolTip())



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


class StubSession:
    """A GPU session whose cost per call is 4 ms plus 1 ms per window, and that runs out of memory at 8 windows."""

    def __init__(self):
        self.calls = 0

    def run(self, outputs, feeds):
        self.calls += 1
        batch = next(iter(feeds.values()))
        if len(batch) >= 8:
            raise RuntimeError('out of GPU memory')
        time.sleep(0.004 + 0.001 * len(batch))
        return [np.zeros((len(batch), 512), dtype=np.float32)]


def stub_embedder():
    from songselector.core.embeddings import OnnxEmbedder
    embedder = OnnxEmbedder.__new__(OnnxEmbedder)
    embedder.spec, embedder.session, embedder.input_name = LAION_CLAP, StubSession(), 'audio'
    embedder.provider, embedder.batch_size, embedder._runtime_version = 'DmlExecutionProvider', 4, 'test'
    return embedder


class GpuUseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_batch_size_is_measured_once_and_remembered(self):
        cache = self.root / 'batch_sizes.json'
        first = stub_embedder()
        self.assertEqual(first.tune(cache), 4)  # 5, 3, 2 ms per window at 1, 2, 4; 8 runs out of memory
        stored = json.loads(cache.read_text())
        self.assertEqual(list(stored.values()), [4])
        self.assertIn(LAION_CLAP.id, next(iter(stored)))
        second = stub_embedder()
        self.assertEqual(second.tune(cache), 4)
        self.assertEqual(second.session.calls, 0)  # read from the cache, nothing measured

    def test_the_cpu_is_not_tuned(self):
        embedder = stub_embedder()
        embedder.provider, embedder.batch_size = 'CPUExecutionProvider', 1
        self.assertEqual(embedder.tune(self.root / 'batch_sizes.json'), 1)
        self.assertFalse((self.root / 'batch_sizes.json').exists())

    def test_two_streams_share_the_work_and_analyse_each_track_once(self):
        cnn14 = EmbeddingStore(self.root / 'embeddings.sqlite')
        tracks = [(canonical_path(str(path)), str(path)) for path in
                  (write_wav(self.root / f'{n}.wav', 2) for n in range(8))]
        analyzer = EmbeddingAnalyzer(cnn14, self.root / 'cnn14.onnx', FakeCnn14)
        analyzer.workers = 2
        analyzer.submit(tracks)
        analyzer.start()
        try:
            self.assertTrue(analyzer.wait_idle(90))
            self.assertEqual(len(analyzer._processes), 2)
        finally:
            analyzer.stop()
        self.assertEqual(cnn14.counts(), (8, 0))
        self.assertFalse(analyzer.running)

    def test_automatic_means_two_streams_on_a_gpu_and_one_on_the_cpu(self):
        analyzer = EmbeddingAnalyzer(EmbeddingStore(self.root / 'e.sqlite'), self.root / 'm.onnx', FakeCnn14)
        analyzer.workers = 'auto'
        self.assertEqual(analyzer._wanted_workers('DmlExecutionProvider'), 2)
        self.assertEqual(analyzer._wanted_workers('CPUExecutionProvider'), 1)
        analyzer.workers = 3
        self.assertEqual(analyzer._wanted_workers('CPUExecutionProvider'), 3)


class DescriptionBarTests(WindowCase):
    """The 'Describe a sound' bar: results in the List (best first), saved prompts, no search."""

    def test_results_show_in_the_list_in_rank_order_and_prompts_can_be_saved(self):
        from songselector.config import HEADER_INDEX, POSITION_COLUMN
        from songselector.ui.list_browser import DESCRIPTION
        window = self.window
        key = canonical_path(str(self.root / 'a.mp3'))
        window._description_model_id = LAION_CLAP.id
        window.show_description_results('warm pads', [('not-in-library', 0.9), (key, 0.5)], 0.02)
        self.assertEqual(window.list_source, {'kind': DESCRIPTION, 'name': 'warm pads'})
        self.assertEqual(window.description_positions, {key: 1})  # the missing track is skipped
        item = window.candidate_tree.topLevelItem(0)
        self.assertEqual(item.text(HEADER_INDEX[POSITION_COLUMN]), '1')
        self.assertIn('warm pads', window.source_label.text())
        self.assertIn('top 1', window.status_label.text())

        window.description_box.setEditText('warm pads')
        window.save_description_prompt()
        self.assertEqual(window.settings['Saved prompts'], ['warm pads'])
        self.assertEqual(window.description_box.findText('warm pads'), 1)  # after the "no search" entry
        window.delete_description_prompt()
        self.assertEqual(window.settings['Saved prompts'], [])
        self.assertEqual(window.description_box.count(), 1)

    def test_the_no_search_entry_shows_all_tracks_again(self):
        from songselector.ui.main_window import NO_DESCRIPTION
        window = self.window
        key = canonical_path(str(self.root / 'a.mp3'))
        window._description_model_id = LAION_CLAP.id
        window.show_description_results('warm pads', [(key, 0.5)], 0.02)
        window.description_box.setEditText('warm pads')
        self.assertEqual(window.description_box.itemText(0), NO_DESCRIPTION)

        window.description_box.setCurrentIndex(0)
        window.description_box.activated.emit(0)
        self.assertIsNone(window.list_source)
        self.assertEqual(window.description_box.currentText(), '')
        self.assertIn('showing all tracks', window.status_label.text())

        window.description_box.setEditText(NO_DESCRIPTION)
        window.delete_description_prompt()  # the entry itself cannot be deleted
        self.assertEqual(window.description_box.itemText(0), NO_DESCRIPTION)
        window.save_description_prompt()  # nor saved as a prompt
        self.assertEqual(window.settings.get('Saved prompts', []), [])

    def test_top_n_recuts_the_last_results_and_the_match_column_shows_the_similarity(self):
        import pandas as pd

        from songselector.config import HEADER_INDEX, MATCH_COLUMN, POSITION_COLUMN
        window = self.window
        paths = [str(self.root / f'{n}.mp3') for n in range(8)]
        window.table = window._load_library(pd.DataFrame([{'Artist': 'A', 'Title': f'T{n}', 'BPM': 128, 'File_Path': path}
                                                          for n, path in enumerate(paths)]))
        window.populate_tree()
        ranked = [(canonical_path(path), 0.5 - n / 100) for n, path in enumerate(paths)]
        window._description_model_id = LAION_CLAP.id
        window.description_count.setValue(5)
        window.show_description_results('warm pads', ranked, 0.02)

        def shown():
            rows = {}
            for index in range(window.candidate_tree.topLevelItemCount()):
                item = window.candidate_tree.topLevelItem(index)
                if not item.isHidden():
                    rows[int(item.text(HEADER_INDEX[POSITION_COLUMN]))] = item.text(HEADER_INDEX[MATCH_COLUMN])
            return rows
        self.assertEqual(shown(), {1: '50%', 2: '49%', 3: '48%', 4: '47%', 5: '46%'})

        with patch.object(window, 'describe') as describe:  # no new search, the kept ranking is cut again
            window.description_count.setValue(7)
            self.assertEqual(len(shown()), 7)
            self.assertEqual(shown()[7], '44%')
            window.description_count.setValue(6)
            self.assertEqual(len(shown()), 6)
        describe.assert_not_called()
        self.assertIn('top 6', window.status_label.text())
        self.assertEqual(window.description_count.text(), '6')  # the number only; "Top" is a label next to it
        window.description_count.setValue(0)  # "All": every analysed track, ranked
        self.assertEqual(window.description_count.text(), 'All')
        self.assertEqual(len(shown()), 8)
        self.assertIn('all 8', window.status_label.text())
        from songselector.ui.tree_widgets import track_sort_key
        self.assertLess(track_sort_key(HEADER_INDEX[MATCH_COLUMN], '9%'), track_sort_key(HEADER_INDEX[MATCH_COLUMN], '31%'))

        window.show_list_source(None)  # all tracks: no ranks, no scores
        item = window.candidate_tree.topLevelItem(0)
        self.assertEqual(item.text(HEADER_INDEX[MATCH_COLUMN]), '')
        window.description_count.setValue(5)  # not showing results: nothing happens
        self.assertIsNone(window.list_source)

    def test_long_messages_and_prompts_do_not_stretch_the_window(self):
        window = self.window
        window.show()
        self.application.processEvents()
        before = window.minimumSizeHint().width()
        long_text = 'a remarkably long description of a deep rolling techno groove with pads ' * 6
        window.status_label.setText(long_text)
        window.embedding_label.setText(long_text)
        window.description_box.setEditText(long_text)
        window.save_description_prompt()
        window._description_model_id = LAION_CLAP.id
        window.show_description_results(long_text, [], 0.02)  # the bar above the List shows the prompt
        self.application.processEvents()
        self.assertLessEqual(window.minimumSizeHint().width(), before)

    def test_enter_in_an_empty_field_shows_all_tracks(self):
        window = self.window
        key = canonical_path(str(self.root / 'a.mp3'))
        window._description_model_id = LAION_CLAP.id
        window.show_description_results('warm pads', [(key, 0.5)], 0.02)
        window.description_box.setEditText('')
        window.describe()
        self.assertIsNone(window.list_source)

    def test_without_a_clap_model_the_bar_says_how_to_get_one(self):
        self.assertFalse(self.window.description_box.isEnabled())
        self.assertIn('Get models', self.window.description_box.lineEdit().placeholderText())


class SearchEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_engine_ranks_the_analysed_tracks_for_a_prompt(self):
        from songselector.ui.text_search_engine import TextSearchEngine
        with tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR']) as folder:
            store = EmbeddingStore(Path(folder) / 'laion.sqlite', spec=LAION_CLAP)
            for index in range(4):
                windows = np.zeros((2, 512), dtype=np.float32)
                windows[:, 0 if index < 2 else 1] = 1
                store.save(f'k{index}', (1, 1), windows)
            engine = TextSearchEngine({LAION_CLAP.id: store}, folder, worker=FakeWorker())
            answers = []
            engine.results.connect(lambda prompt, ranked, seconds: answers.append((prompt, ranked)))
            engine.search(LAION_CLAP.id, 'deep dnb')
            deadline = time.monotonic() + 20
            while not answers and time.monotonic() < deadline:
                self.application.processEvents()
                time.sleep(0.01)
            prompt, ranked = answers[0]
            self.assertEqual(prompt, 'deep dnb')
            self.assertEqual({key for key, _ in ranked[:2]}, {'k0', 'k1'})
            self.assertEqual(len(ranked), 4)

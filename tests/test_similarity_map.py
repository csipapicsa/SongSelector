"""Track similarity, the 2D map layout and the similarity map view."""
import copy
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from traktor_key_calculator.core.embeddings import EmbeddingStore
from traktor_key_calculator.core.similarity import (EDGE_SAME_COLOR, EDGE_SAME_RATING, connection, display_color,
                                                    nearest, place_new, track_vectors, tsne_layout)
from traktor_key_calculator.core.traktor_collection import canonical_path


def two_styles(per_style=12, frames=6, seed=0):
    """Fake embedding matrices for two clearly different 'styles' (ReLU-like, non-negative)."""
    rng = np.random.default_rng(seed)
    centres = [rng.random(2048) * (rng.random(2048) > 0.85) for _ in range(2)]
    return [np.maximum(centres[style] + rng.normal(0, 0.05, (frames, 2048)), 0).astype(np.float16)
            for style in (0, 1) for _ in range(per_style)]


class SimilarityTests(unittest.TestCase):
    def test_track_vectors_are_unit_length_and_cluster_by_style(self):
        vectors = track_vectors(two_styles())
        self.assertEqual(vectors.shape, (24, 4096))
        np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, rtol=1e-5)
        for index in (0, 13):
            same_style = {row for row, _ in nearest(vectors, index, count=5)}
            self.assertTrue(all((row < 12) == (index < 12) for row in same_style))

    def test_nearest_is_sorted_excludes_itself_and_respects_among(self):
        vectors = track_vectors(two_styles())
        result = nearest(vectors, 0, count=30)
        self.assertEqual(len(result), 23)
        self.assertNotIn(0, [row for row, _ in result])
        self.assertEqual([score for _, score in result], sorted((score for _, score in result), reverse=True))
        self.assertEqual({row for row, _ in nearest(vectors, 0, count=30, among=[0, 15, 16])}, {15, 16})

    def test_tsne_keeps_the_styles_apart(self):
        vectors = track_vectors(two_styles())
        points = tsne_layout(vectors, iterations=400)
        self.assertEqual(points.shape, (24, 2))
        first, second = points[:12], points[12:]
        within = np.mean([np.linalg.norm(first - first.mean(0), axis=1).mean(), np.linalg.norm(second - second.mean(0), axis=1).mean()])
        self.assertGreater(np.linalg.norm(first.mean(0) - second.mean(0)), 2 * within)
        self.assertIsNone(tsne_layout(vectors, should_stop=lambda: True))
        self.assertEqual(tsne_layout(vectors[:2]).shape, (2, 2))

    def test_new_tracks_are_placed_near_their_most_similar_tracks(self):
        vectors = track_vectors(two_styles())
        known = np.array([[0.0, 0.0]] * 12 + [[100.0, 100.0]] * 11, dtype=np.float32)
        placed = place_new(known, vectors[:23], vectors[23:])
        np.testing.assert_allclose(placed[0], [100, 100], atol=1e-3)

    def test_edge_rules_use_tempo_adjusted_keys_and_own_colour_first(self):
        a = {'Camelot Key New': '8A', 'Color': '5', 'Color - Song Selector': '', 'Rating': '4'}
        b = {'Camelot Key New': '9A', 'Color': '1', 'Color - Song Selector': '5', 'Rating - Song Selector': '4'}
        self.assertEqual(connection(a, b, {'plus_1_mix'}), 'plus_1_mix')
        self.assertIsNone(connection(a, b, {'minus_1_mix'}))
        self.assertEqual(display_color(b), 5)  # own colour wins over Traktor's
        self.assertEqual(connection(a, b, {EDGE_SAME_COLOR}), EDGE_SAME_COLOR)
        self.assertEqual(connection(a, b, {EDGE_SAME_RATING}), EDGE_SAME_RATING)
        self.assertIsNone(connection({'Camelot Key New': 'Unknown'}, b, {'plus_1_mix'}))


class LayoutStoreTests(unittest.TestCase):
    def test_load_many_and_layout_round_trip(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TRAKTOR_APP_DATA_DIR']) as folder:
            store = EmbeddingStore(Path(folder) / 'embeddings.sqlite')
            store.save('a', (1, 1), np.ones((2, 2048)))
            store.save('b', (1, 1), np.zeros((3, 2048)))
            store.save_error('c', (1, 1), 'broken')
            self.assertEqual(sorted(store.load_many()), ['a', 'b'])
            self.assertEqual(list(store.load_many(['b'])), ['b'])
            store.save_layout({'a': (1.5, 2.5), 'b': (-1, 0)})
            self.assertEqual(store.load_layout(), {'a': (1.5, 2.5), 'b': (-1.0, 0.0)})
            store.save_layout({'a': (0, 0)})
            self.assertEqual(store.load_layout(), {'a': (0.0, 0.0)})


class SimilarityMapGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        from traktor_key_calculator.config import SETTINGS_DEFAULT
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['TRAKTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)
        settings = copy.deepcopy(SETTINGS_DEFAULT)
        settings.update({'Traktor collection': '', 'Advanced search': {'enabled': False, 'filters': []}, 'Master Tempo': 128})
        (self.root / 'settings.json').write_text(json.dumps(settings))
        # 24 analysed tracks in two styles plus one not analysed; keys spread over the wheel.
        rows = []
        for index in range(25):
            style = 'breaks' if index < 12 else 'dnb'
            rows.append({'Artist': f'{style} artist', 'Title': f'{style} {index}', 'BPM': 128,
                         'File_Path': str(self.root / f'track{index}.mp3'), 'Genre': style,
                         'Musical_Key_Base': ['A', 'E', 'B'][index % 3], 'BaseMinorOrMajor': 'minor',
                         'Color': index % 3})
        self.library = pd.DataFrame(rows)
        store = EmbeddingStore(self.root / 'embeddings.sqlite')
        for index, matrix in enumerate(two_styles()):
            store.save(canonical_path(rows[index]['File_Path']), (1, 1), matrix)
        self.patches = [
            patch('traktor_key_calculator.ui.main_window.SETTINGS_FILE', str(self.root / 'settings.json')),
            patch('traktor_key_calculator.ui.main_window.DataManager.load_default_data',
                  side_effect=lambda: self.library.copy()),
        ]
        for active in self.patches:
            active.start()
        from traktor_key_calculator.ui.main_window import TraktorKeyCalculator
        self.window = TraktorKeyCalculator()
        self.map = self.window.similarity_map
        self.window.library_tabs.setCurrentWidget(self.map)
        deadline = time.monotonic() + 60
        while self.map._loading and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.02)
        self.application.processEvents()

    def tearDown(self):
        self.window.close()
        self.application.processEvents()
        for active in self.patches:
            active.stop()
        self.temp.cleanup()

    def key(self, index):
        return canonical_path(self.root / f'track{index}.mp3')

    def visible(self):
        return {key for key, dot in self.map.dots.items() if dot.isVisible()}

    def test_map_shows_analysed_tracks_of_the_filtered_list_and_keeps_positions(self):
        self.assertEqual(len(self.visible()), 24)
        self.assertIn('1 listed tracks are not analysed yet', self.map.status.text())
        before = self.map.dots[self.key(0)].pos()
        self.window.search_bar.setText('breaks')
        self.assertEqual(self.visible(), {self.key(i) for i in range(12)})
        self.assertEqual(self.map.dots[self.key(0)].pos(), before)  # filtering never moves dots
        self.window.search_bar.clear()
        self.assertEqual(len(self.visible()), 24)
        self.assertEqual(len(EmbeddingStore(self.root / 'embeddings.sqlite').load_layout()), 24)  # cached

    def test_selecting_a_track_lists_and_rings_its_closest_matches(self):
        self.map.select(self.key(0))
        matches = [self.map.suggestions.topLevelItem(i).data(0, 0x0100) for i in range(self.map.suggestions.topLevelItemCount())]
        self.assertEqual(len(matches), 15)
        self.assertTrue(all(int(key.split('track')[-1].split('.')[0]) < 12 for key in matches[:11]))  # same style first
        self.assertEqual(self.map.match_keys, matches)
        self.assertEqual(self.map.dots[matches[0]].pen().color().name(), '#40e0ff')
        self.assertEqual(self.window.candidate_tree.currentItem().text(1), 'breaks 0')  # list follows

    def test_edges_follow_the_chosen_criteria(self):
        self.map.select(self.key(0))
        for name, action in self.map.edge_actions.items():
            action.setChecked(name == 'perfect_mix')
        edges = self.map._edges(self.map.criteria())
        # same tempo-adjusted key as track 0 (keys repeat every 3 tracks)
        self.assertEqual({target for _, target, _ in edges}, {self.key(i) for i in range(3, 24, 3)})
        self.assertTrue(self.map.edge_items)
        self.map.all_edges.setChecked(True)
        self.assertEqual(len(self.map._edges(self.map.criteria())), 3 * 28)  # 3 key groups of 8 tracks
        self.assertEqual(self.window.settings['Map edges'], ['perfect_mix'])

    def test_hover_shows_the_configured_details_and_double_click_adds_to_playlist(self):
        dot = self.map.dots[self.key(5)]
        self.assertIn('Title: breaks 5', dot.toolTip())
        self.assertIn('Genre: breaks', dot.toolTip())
        self.window.settings['Map hover fields'] = ['Original Key']
        self.window._refresh_map()
        self.assertEqual(dot.toolTip(), 'Original Key: B minor')  # track 5: keys cycle A, E, B
        self.map.request_add_to_playlist.emit(self.key(5))
        self.assertEqual(self.window.playlist_tree.topLevelItem(0).text(1), 'breaks 5')
        self.assertFalse(dot.isVisible())  # playlist tracks leave the library view, as in the list

    def test_hover_fields_dialog_returns_checked_columns_in_table_order(self):
        from traktor_key_calculator.ui.map_settings_dialog import HoverFieldsDialog
        dialog = HoverFieldsDialog(['Title', 'Artist'], ['Artist', 'Title', 'Genre'])
        dialog.boxes['Genre'].setChecked(True)
        self.assertEqual(dialog.selected(), ['Artist', 'Title', 'Genre'])

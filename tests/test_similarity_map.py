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


class ClusteringTests(unittest.TestCase):
    def test_kmeans_and_communities_find_the_two_styles(self):
        from traktor_key_calculator.core.clustering import group_tracks
        vectors = track_vectors(two_styles(per_style=20))
        for method, parameter in (('kmeans', 2), ('communities', 1.0)):
            labels = group_tracks(method, vectors, np.zeros((40, 2)), parameter)
            self.assertEqual(len(set(labels[:20])), 1, method)
            self.assertEqual(len(set(labels[20:])), 1, method)
            self.assertNotEqual(labels[0], labels[20], method)

    def test_density_groups_the_clumps_and_leaves_scattered_points_out(self):
        from traktor_key_calculator.core.clustering import group_tracks
        rng = np.random.default_rng(1)
        clumps = [rng.normal(centre, 0.3, (40, 2)) for centre in ((0, 0), (10, 0))]
        scattered = np.array([[5, 8], [-6, -7], [14, 9]])
        labels = group_tracks('density', np.zeros((83, 4)), np.vstack(clumps + [scattered]), 50)
        self.assertEqual(len(set(labels[:40]) - {-1}), 1)
        self.assertEqual(len(set(labels[40:80]) - {-1}), 1)
        self.assertNotEqual(set(labels[:40]) - {-1}, set(labels[40:80]) - {-1})
        self.assertEqual(list(labels[80:]), [-1, -1, -1])

    def test_groups_are_numbered_by_size(self):
        from traktor_key_calculator.core.clustering import _by_size
        self.assertEqual(list(_by_size([5, 7, 7, -1, 7, 5, 2])), [1, 0, 0, -1, 0, 1, 2])


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


class MapWindowTestBase(unittest.TestCase):
    """Window with 25 library tracks (24 analysed, two styles) and the map tab open; no tests here."""

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

class SimilarityMapGuiTests(MapWindowTestBase):
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
        self.assertEqual(len(matches), 23)  # all other analysed tracks: fewer than the default 50
        self.assertTrue(all(int(key.split('track')[-1].split('.')[0]) < 12 for key in matches[:11]))  # same style first
        self.assertEqual(self.map.match_keys, matches[:15])  # only the most similar are ringed
        self.assertEqual(self.map.dots[matches[0]].pen().color().name(), '#40e0ff')
        self.assertEqual(self.window.candidate_tree.currentItem().text(1), 'breaks 0')  # list follows

    def test_edges_follow_the_chosen_criteria(self):
        self.map.select(self.key(0))
        for name, action in self.map.edge_actions.items():
            action.setChecked(name == 'perfect_mix')
        edges = self.map._edges(self.map.criteria())
        # same tempo-adjusted key as track 0 (keys repeat every 3 tracks)
        self.assertEqual({target for _, target, *_ in edges}, {self.key(i) for i in range(3, 24, 3)})
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
        self.assertTrue(dot.isVisible())  # playlist tracks stay in the library view (dimmed in the list)

    def test_hover_fields_dialog_returns_checked_columns_in_table_order(self):
        from traktor_key_calculator.ui.map_settings_dialog import HoverFieldsDialog
        dialog = HoverFieldsDialog(['Title', 'Artist'], ['Artist', 'Title', 'Genre'])
        dialog.boxes['Genre'].setChecked(True)
        self.assertEqual(dialog.selected(), ['Artist', 'Title', 'Genre'])


class SimilarityMapInteractionTests(MapWindowTestBase):
    """Selection details, previewing matches, dragging files out, sorting."""

    def matches(self):
        tree = self.map.suggestions
        return [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]

    def test_click_on_a_match_highlights_it_double_click_selects_it(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        self.window.resize(1400, 900)
        self.window.show()
        self.application.processEvents()
        self.map.select(self.key(0))
        tree = self.map.suggestions
        first = self.matches()[0]
        match = first.data(0, 0x0100)
        QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=tree.visualItemRect(first).center())
        self.application.processEvents()
        self.assertEqual(self.map.selected_key, self.key(0))  # the selection stays
        self.assertEqual(self.map.preview_key, match)
        self.assertEqual(self.map.dots[match].pen().color().name(), '#ff2bd6')
        self.assertTrue(self.map.preview_glow.isVisible())
        self.assertEqual(self.map.preview_glow.pos(), self.map.dots[match].pos())
        self.assertEqual(self.map.selected_glow.pos(), self.map.dots[self.key(0)].pos())
        self.assertEqual([item.data(0, 0x0100) for item in self.matches()][0], match)  # list unchanged
        QTest.mouseDClick(tree.viewport(), Qt.LeftButton, pos=tree.visualItemRect(first).center())
        self.application.processEvents()
        self.assertEqual(self.map.selected_key, match)
        self.assertEqual(self.map.dots[match].pen().color().name(), '#ffffff')
        self.assertIsNone(self.map.preview_key)
        self.assertFalse(self.map.preview_glow.isVisible())
        self.assertEqual(self.map.selected_glow.pos(), self.map.dots[match].pos())  # the white glow moved
        self.assertNotIn(match, [item.data(0, 0x0100) for item in self.matches()])  # its own matches now
        self.assertEqual(self.window.playlist_tree.topLevelItemCount(), 0)  # does not add to the playlist

    def test_clicked_match_gets_pale_edges_next_to_the_selected_tracks_edges(self):
        for name, action in self.map.edge_actions.items():
            action.setChecked(name == 'perfect_mix')
        self.map.select(self.key(0))
        alphas = lambda: {item.pen().color().alpha() for item in self.map.edge_items}
        self.assertEqual(max(alphas()), 170)  # the selected track's strongest edges
        self.assertNotIn(85, alphas())
        other_key_group = next(item.data(0, 0x0100) for item in self.matches()
                               if int(item.data(0, 0x0100).split('track')[-1].split('.')[0]) % 3 == 1)
        self.map.preview(other_key_group)
        self.assertIn(85, alphas())  # the clicked match's strongest edges: half of 170
        self.assertEqual(max(alphas()), 170)
        self.map.harmonic_only.setChecked(True)  # the list is rebuilt: highlight and pale edges go
        self.assertIsNone(self.map.preview_key)
        self.assertNotIn(85, alphas())

    def test_matches_on_the_playlist_are_italic(self):
        self.map.request_add_to_playlist.emit(self.key(1))
        self.map.select(self.key(0))
        italic = {item.data(0, 0x0100) for item in self.matches() if item.font(0).italic()}
        self.assertEqual(italic, {self.key(1)})

    def test_harmonic_only_keeps_tracks_without_a_key(self):
        self.map.harmonic_only.setChecked(True)
        fields = {key: dict(values) for key, values in self.map.listed.items()}
        fields[self.key(1)]['Camelot Key New'] = 'Unknown'  # not analysed in Traktor
        self.map.set_tracks(fields)
        self.map.select(self.key(0))
        mixes = {item.data(0, 0x0100): item.text(1) for item in self.matches()}
        self.assertEqual(mixes[self.key(1)], 'no key')
        self.assertTrue(all(text for text in mixes.values()))  # every other match is harmonic
        fields[self.key(0)]['Camelot Key New'] = 'Unknown'  # the selected track itself has no key
        self.map.set_tracks(fields)
        self.map.select(self.key(0))
        self.assertEqual(len(self.matches()), 23)  # all others
        self.assertEqual({item.text(1) for item in self.matches()}, {'no key'})

    def test_matches_panel_stays_visible_on_a_narrow_window_and_keeps_its_width(self):
        # Long one-line texts (status, caption) used to set the minimum width: the map grew wider
        # than the window and the splitter collapsed the matches panel to nothing.
        bars = self.map.layout().itemAt(0).minimumSize().width() + 40
        self.window.resize(bars, 900)
        self.window.show()
        self.application.processEvents()
        self.assertLessEqual(self.map.width(), self.window.width())
        self.assertGreaterEqual(self.map.splitter.sizes()[1], 220)
        self.map.splitter.moveSplitter(self.map.splitter.width() - 400, 1)
        self.assertEqual(self.window.settings['Map splitter'], self.map.splitter.sizes())

    def test_selected_track_glows_white_until_it_is_filtered_out(self):
        self.map.select(self.key(4))
        self.assertTrue(self.map.selected_glow.isVisible())
        self.assertEqual(self.map.selected_glow.pos(), self.map.dots[self.key(4)].pos())
        self.window.search_bar.setText('dnb')
        self.assertFalse(self.map.selected_glow.isVisible())

    def test_edges_go_to_the_most_similar_partners_more_similar_more_opaque(self):
        for name, action in self.map.edge_actions.items():
            action.setChecked(name in ('perfect_mix', 'plus_1_mix', 'minus_1_mix', 'energy_boost'))
        self.map.select(self.key(0))
        partners = self.map._edges(self.map.criteria())
        self.assertEqual(len(partners), 20)  # 23 harmonic partners, the 20 most similar kept
        self.map.lines_per_track.setValue(5)
        edges = self.map._edges(self.map.criteria())
        self.assertEqual([target for _, target, *_ in edges], [target for _, target, *_ in partners[:5]])
        similarity = [value for *_, value in partners]
        self.assertEqual(similarity, sorted(similarity, reverse=True))
        self.assertEqual(self.window.settings['Map lines per track'], 5)
        self.map.lines_per_track.setValue(20)
        alphas = sorted({item.pen().color().alpha() for item in self.map.edge_items})
        self.assertEqual((alphas[0], alphas[-1]), (round(170 * 0.15), 170))  # weakest faint, strongest full

    def wait_for_groups(self):
        deadline = time.monotonic() + 30
        while self.map.grouping_summary.text() == 'Grouping...' and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)

    def test_grouping_colours_dots_by_group_and_off_restores_traktor_colours(self):
        traktor = {key: dot.brush().color().name() for key, dot in self.map.dots.items()}
        self.map.grouping.setCurrentIndex(self.map.grouping.findData('kmeans'))
        self.map.grouping_parameter.setValue(2)
        self.wait_for_groups()
        self.assertIn('2 groups of all 24 analysed tracks', self.map.grouping_summary.text())
        groups = {self.map.groups[self.key(i)] for i in range(12)}, {self.map.groups[self.key(i)] for i in range(12, 24)}
        self.assertEqual(len(groups[0]), 1)  # each style is one group
        self.assertEqual(len(groups[1]), 1)
        self.assertNotEqual(groups[0], groups[1])
        colours = {dot.brush().color().name() for key, dot in self.map.dots.items() if dot.isVisible()}
        self.assertEqual(colours, {'#e6194b', '#3cb44b'})
        self.assertIn('Group ', self.map.dots[self.key(0)].toolTip())
        self.assertEqual(self.window.settings['Map grouping'], 'kmeans')
        self.assertEqual(self.window.settings['Map grouping parameters']['kmeans'], 2)
        self.map.grouping.setCurrentIndex(0)
        self.assertEqual({key: dot.brush().color().name() for key, dot in self.map.dots.items()}, traktor)
        self.assertFalse(self.map.grouping_parameter.isVisible())

    def test_every_grouping_method_runs_on_the_map(self):
        for method in ('kmeans', 'communities', 'density'):
            self.map.grouping.setCurrentIndex(self.map.grouping.findData(method))
            self.wait_for_groups()
            self.assertEqual(set(self.map.groups), set(self.map.data.keys), method)
            self.assertIn('groups of all 24', self.map.grouping_summary.text(), method)

    def test_selected_track_shows_details_box_and_label_on_the_map(self):
        self.map.select(self.key(4))
        self.assertTrue(self.map.label.isVisible())
        self.assertIn('breaks artist - breaks 4', self.map.label_text.text())
        self.assertIn('master tempo', self.map.label_text.text())
        self.assertIn('breaks 4', self.map.details.text())
        self.assertIn('Genre', self.map.details.text())
        self.window.search_bar.setText('dnb')  # the selected track is filtered out
        self.assertFalse(self.map.label.isVisible())

    def test_matches_and_dots_drag_their_files(self):
        for index in range(24):
            (self.root / f'track{index}.mp3').write_bytes(b'')
        self.map.select(self.key(0))
        items = self.matches()[:2]
        urls = [url.toLocalFile() for url in self.map.suggestions.mimeData(items).urls()]
        self.assertEqual([Path(url) for url in urls], [Path(item.data(0, 0x0101)) for item in items])
        dragged = []
        with patch('traktor_key_calculator.ui.similarity_map.QDrag.exec_',
                   lambda drag, *args: dragged.append(drag.mimeData().urls()) or 1):
            self.map.drag_files([self.key(3)])
        self.assertEqual(Path(dragged[0][0].toLocalFile()), self.root / 'track3.mp3')

    def test_edge_cap_message_disappears_when_no_longer_true(self):
        with patch('traktor_key_calculator.ui.similarity_map.MAX_EDGES', 5):
            self.map.all_edges.setChecked(True)
            self.assertIn('Showing the first 5 edges', self.map.status.text())
            self.map.all_edges.setChecked(False)
            self.assertNotIn('Showing the first', self.map.status.text())

    def test_match_columns_sort_by_number_and_name_both_ways(self):
        self.map.select(self.key(0))
        scores = [item.data(0, 0x0102) for item in self.matches()]
        self.assertEqual(scores, sorted(scores, reverse=True))  # default: most similar first
        self.map.suggestions.sortByColumn(0, 0)  # Qt.AscendingOrder
        scores = [item.data(0, 0x0102) for item in self.matches()]
        self.assertEqual(scores, sorted(scores))
        self.map.suggestions.sortByColumn(3, 1)  # title, descending
        titles = [item.text(3).casefold() for item in self.matches()]
        self.assertEqual(titles, sorted(titles, reverse=True))
        self.map.select(self.key(13))  # the chosen sort is kept for the next track
        titles = [item.text(3).casefold() for item in self.matches()]
        self.assertEqual(titles, sorted(titles, reverse=True))


    def test_number_of_matches_can_be_chosen_and_is_remembered(self):
        self.map.match_count.setValue(5)
        self.map.select(self.key(0))
        self.assertEqual(len(self.matches()), 5)
        self.assertEqual(len(self.map.match_keys), 5)
        self.assertEqual(self.window.settings['Map match count'], 5)

    def test_match_columns_can_be_chosen_ratings_as_stars_and_numbers_sort(self):
        from traktor_key_calculator.ui.similarity_map import DEFAULT_MATCH_COLUMNS, MATCH_COLUMNS
        tree = self.map.suggestions
        shown = [name for column, name in enumerate(MATCH_COLUMNS) if not tree.isColumnHidden(column)]
        self.assertEqual(shown, DEFAULT_MATCH_COLUMNS)
        bpm, color = MATCH_COLUMNS.index('Original BPM'), MATCH_COLUMNS.index('Color')
        tree.show_column(bpm, True)
        tree.show_column(color, True)
        tree.show_column(MATCH_COLUMNS.index('Mix'), False)
        self.assertEqual(self.window.settings['Map match columns'],
                         ['Similarity', 'Artist', 'Title', 'Original BPM', 'Color'])
        self.map.select(self.key(0))
        self.assertEqual(self.matches()[0].text(bpm), '128')
        self.assertEqual(self.matches()[0].data(bpm, 0x0102), 128.0)
        tree.sortByColumn(color, 0)  # Qt.AscendingOrder: by colour number
        colours = [int(item.text(color)) for item in self.matches()]
        self.assertEqual(colours, sorted(colours))
        rating = MATCH_COLUMNS.index('Rating')
        delegate = tree.itemDelegateForColumn(rating)
        self.assertEqual(delegate.displayText('3', None), '★★★☆☆')


class ShownFieldsTests(unittest.TestCase):
    def test_empty_values_and_colour_zero_are_not_shown(self):
        from traktor_key_calculator.ui.similarity_map import shown_fields
        fields = {'Artist': 'A', 'Genre': '', 'Color': '0', 'Color - Song Selector': '5', 'Rating': '0',
                  'Rating - Song Selector': '4'}
        names = ['Artist', 'Genre', 'Color', 'Color - Song Selector', 'Rating', 'Rating - Song Selector', 'Comment']
        self.assertEqual(shown_fields(fields, names),
                         [('Artist', 'A'), ('Color - Song Selector', '5'), ('Rating - Song Selector', '★★★★☆')])


class MapDropTests(MapWindowTestBase):
    """Dropping a track on the map (e.g. from the playlist) selects it there."""

    def drop_on_map(self, *paths):
        from PyQt5.QtCore import QCoreApplication, QMimeData, QPoint, QPointF, Qt, QUrl
        from PyQt5.QtGui import QDragEnterEvent, QDropEvent
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        viewport = self.map.view.viewport()
        enter = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QCoreApplication.sendEvent(viewport, enter)
        self.assertTrue(enter.isAccepted())
        QCoreApplication.sendEvent(viewport, QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
        self.application.processEvents()

    def test_playlist_track_dropped_on_the_map_is_shown_selected_and_matched(self):
        self.window.hide_playlist_action.setChecked(True)  # playlist tracks hidden from list and map
        self.map.request_add_to_playlist.emit(self.key(2))  # now on the playlist, hidden on the map
        self.assertFalse(self.map.dots[self.key(2)].isVisible())
        self.drop_on_map(self.root / 'track2.mp3')
        self.assertEqual(self.map.selected_key, self.key(2))
        self.assertTrue(self.map.dots[self.key(2)].isVisible())
        self.assertIn('breaks 2', self.map.label_text.text())
        self.assertIn('Not in the list view', self.map.details.text())
        matches = {self.map.suggestions.topLevelItem(i).data(0, 0x0100) for i in range(self.map.suggestions.topLevelItemCount())}
        self.assertNotIn(self.key(2), matches)
        self.assertTrue(matches <= set(self.map.listed))  # matches come from the list
        self.window.search_bar.setText('breaks')  # filtering keeps the selected reference
        self.assertTrue(self.map.dots[self.key(2)].isVisible())
        self.map.select(self.key(5))  # another track: the reference dot goes away again
        self.assertFalse(self.map.dots[self.key(2)].isVisible())
        self.assertIsNone(self.map.reference)

    def test_listed_track_dropped_is_simply_selected_and_unanalysed_is_reported(self):
        self.drop_on_map(self.root / 'track7.mp3')
        self.assertEqual(self.map.selected_key, self.key(7))
        self.assertIsNone(self.map.reference)
        self.drop_on_map(self.root / 'track24.mp3')  # in the library, but not analysed
        self.assertEqual(self.map.selected_key, self.key(7))
        self.assertIn('track24.mp3 is not on the map yet', self.map.status.text())

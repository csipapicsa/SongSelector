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

from songselector.core.embeddings import EmbeddingStore
from songselector.core.similarity import (
    EDGE_SAME_COLOR,
    EDGE_SAME_RATING,
    connection,
    display_color,
    nearest,
    place_new,
    track_vectors,
    tsne_layout,
)
from songselector.core.traktor_collection import canonical_path


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

    def test_tsne_and_placing_work_in_3d(self):
        vectors = track_vectors(two_styles())
        points = tsne_layout(vectors, iterations=400, dims=3)
        self.assertEqual(points.shape, (24, 3))
        first, second = points[:12], points[12:]
        within = np.mean([np.linalg.norm(first - first.mean(0), axis=1).mean(), np.linalg.norm(second - second.mean(0), axis=1).mean()])
        self.assertGreater(np.linalg.norm(first.mean(0) - second.mean(0)), 2 * within)
        known = np.array([[0.0, 0.0, 0.0]] * 12 + [[100.0, 100.0, 100.0]] * 11, dtype=np.float32)
        np.testing.assert_allclose(place_new(known, vectors[:23], vectors[23:])[0], [100, 100, 100], atol=1e-3)
        self.assertEqual(place_new(known, vectors[:23], vectors[:0]).shape, (0, 3))

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
        from songselector.core.clustering import group_tracks
        vectors = track_vectors(two_styles(per_style=20))
        for method, parameter in (('kmeans', 2), ('communities', 1.0)):
            labels = group_tracks(method, vectors, np.zeros((40, 2)), parameter)
            self.assertEqual(len(set(labels[:20])), 1, method)
            self.assertEqual(len(set(labels[20:])), 1, method)
            self.assertNotEqual(labels[0], labels[20], method)

    def test_density_groups_the_clumps_and_leaves_scattered_points_out(self):
        from songselector.core.clustering import group_tracks
        rng = np.random.default_rng(1)
        clumps = [rng.normal(centre, 0.3, (40, 2)) for centre in ((0, 0), (10, 0))]
        scattered = np.array([[5, 8], [-6, -7], [14, 9]])
        labels = group_tracks('density', np.zeros((83, 4)), np.vstack(clumps + [scattered]), 50)
        self.assertEqual(len(set(labels[:40]) - {-1}), 1)
        self.assertEqual(len(set(labels[40:80]) - {-1}), 1)
        self.assertNotEqual(set(labels[:40]) - {-1}, set(labels[40:80]) - {-1})
        self.assertEqual(list(labels[80:]), [-1, -1, -1])

    def test_groups_are_numbered_by_size(self):
        from songselector.core.clustering import _by_size
        self.assertEqual(list(_by_size([5, 7, 7, -1, 7, 5, 2])), [1, 0, 0, -1, 0, 1, 2])

    def test_groups_are_numbered_along_the_map(self):
        # Asked 2026-11-17: neighbouring groups got far-apart numbers (by size). Centres on a line at x = 0, 10, 1,
        # 11 (two pairs of neighbours): the path starts at the outermost centre and steps to the nearest.
        from songselector.core.clustering import by_position
        labels = [0, 0, 1, 1, 2, 2, 3, 3, -1]
        points = [(0, 0), (0, 1), (10, 0), (10, 1), (1, 0), (1, 1), (11, 0), (11, 1), (5, 5)]
        numbers = by_position(labels, points)
        self.assertEqual(numbers[-1], -1)
        by_x = {x: numbers[labels.index(group)] for group, x in ((0, 0), (1, 10), (2, 1), (3, 11))}
        self.assertEqual(sorted(by_x.values()), [0, 1, 2, 3])
        # neighbours on the map have neighbouring numbers
        self.assertEqual(abs(by_x[0] - by_x[1]), 1)
        self.assertEqual(abs(by_x[10] - by_x[11]), 1)
        self.assertEqual(list(by_position([1, 0, 0], [(0, 0)])), [1, 0, 0])  # positions do not fit: by size
        self.assertEqual(list(by_position([4, 4, -1], [(0, 0), (1, 1), (2, 2)])), [0, 0, -1])

    def test_group_colours_repeat_instead_of_turning_grey(self):
        from PyQt5.QtGui import QColor

        from songselector.ui.similarity_map import GROUP_COLOURS, UNGROUPED, group_colour
        self.assertEqual(group_colour(len(GROUP_COLOURS)).name(), group_colour(0).name())
        self.assertEqual(group_colour(30).name(), QColor(GROUP_COLOURS[30 % len(GROUP_COLOURS)]).name())
        self.assertEqual(group_colour(-1), UNGROUPED)


class LayoutStoreTests(unittest.TestCase):
    def test_load_many_and_layout_round_trip(self):
        with tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR']) as folder:
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
        from songselector.config import SETTINGS_DEFAULT
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
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
            patch('songselector.ui.main_window.SETTINGS_FILE', str(self.root / 'settings.json')),
            patch('songselector.ui.main_window.DataManager.load_default_data',
                  side_effect=lambda: self.library.copy()),
        ]
        for active in self.patches:
            active.start()
        from songselector.ui.main_window import MainWindow
        self.window = MainWindow()
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
        self.map.hover(self.key(5))
        card = self.map.hover_card
        self.assertTrue(card.isVisible())
        self.assertEqual(card.pos(), dot.pos())
        self.assertIn('Title\nbreaks 5', card.text.toPlainText())
        self.assertIn('Genre\nbreaks', card.text.toPlainText())
        self.window.settings['Map hover fields'] = ['Original Key']
        self.window._refresh_map()  # the card is rebuilt while the mouse stays on the dot
        self.assertIn('Original Key\nB minor', card.text.toPlainText())  # track 5: keys cycle A, E, B
        self.assertNotIn('Genre', card.text.toPlainText())
        self.map.hover(None)
        self.assertFalse(card.isVisible())
        self.map.request_add_to_playlist.emit(self.key(5))
        self.assertEqual(self.window.playlist_tree.topLevelItem(0).text(1), 'breaks 5')
        self.assertTrue(dot.isVisible())  # playlist tracks stay in the library view (dimmed in the list)

    def test_one_toolbar_by_task(self):
        # UI review 2026-11-20: one toolbar (what is mapped -> colours -> view) that folds into its >> menu
        # instead of forcing a width (the two rows before made the map at least ~1,700 px wide). Later that day the
        # user moved the model choice to the main window (next to "Describe a sound") and dropped "Own window".
        self.assertLess(self.map.minimumSizeHint().width(), 900)
        toolbar_widgets = [self.map.toolbar.widgetForAction(action) for action in self.map.toolbar.actions()]
        order = [self.map.only_button, self.map.grouping, self.map.edges_button, self.map.view_3d_button,
                 self.map.rearrange_button]
        self.assertEqual([widget for widget in toolbar_widgets if widget in order], order)
        self.assertNotIn(self.map.match_filter, toolbar_widgets)  # it sits with the closest matches it filters
        self.assertNotIn(self.map.detach_button, toolbar_widgets)
        self.assertFalse(hasattr(self.map, 'model_box'))
        # Later that day: the toolbar moved below the map, the last row (user's request).
        layout = self.map.layout()
        self.assertEqual(layout.indexOf(self.map.toolbar), layout.count() - 1)
        self.assertGreater(layout.indexOf(self.map.toolbar), layout.indexOf(self.map.splitter))
        self.assertNotIn('Scroll: zoom', self.map.status.text())  # the how-to is behind the ? button
        self.assertIn('Scroll: zoom', self.map.help_button.toolTip())

    def test_the_map_window_has_its_own_search_that_decides_the_map(self):
        self.window.search_bar.setText('breaks 1')  # the List: tracks 1, 10-19
        self.window.set_map_detached(True)
        try:
            listed = set(self.map.listed)
            self.map_window_search('breaks 2')
            self.assertEqual(set(self.map.listed), {key for key in self.map.dots if 'breaks 2' in self.title(key)})
            self.assertNotEqual(set(self.map.listed), listed)
            self.assertIn('own search "breaks 2"', self.map.status.text())
            self.assertEqual(self.window.search_bar.text(), 'breaks 1')  # the List keeps its own search
            self.map_window_search('')
            self.assertEqual(set(self.map.listed), listed)  # empty: the map follows the List again
        finally:
            self.window.set_map_detached(False)

    def map_window_search(self, text):
        self.window.map_window.search.setText(text)
        self.window.map_window.search_changed.emit()  # what the typing pause sends

    def title(self, key):
        return self.window._fields_for_key(key).get('Title', '')

    def test_map_details_dialog_returns_each_places_checked_items_in_row_order(self):
        from songselector.ui.map_settings_dialog import MapDetailsDialog
        dialog = MapDetailsDialog({'card': ['Title', 'Artist'], 'panel': ['Cover art']},
                                  {'card': 'Card', 'panel': 'Panel'},
                                  [('On the map', {'Cover art': 'tip'}), ('Columns', {'Artist': '', 'Title': '', 'Genre': ''})],
                                  {'panel': {'Genre'}}, width=50)
        dialog.boxes['card', 'Genre'].setChecked(True)
        self.assertNotIn(('panel', 'Genre'), dialog.boxes)  # does not apply there: no box
        self.assertEqual(dialog.selected(), {'card': ['Artist', 'Title', 'Genre'], 'panel': ['Cover art']})
        self.assertEqual(dialog.info_width(), 200)  # never narrower than the minimum

    def test_info_boxes_wrap_long_file_names_at_the_set_width(self):
        # Reported 2026-11-20: a track named by its long file name made its card and label as wide as the map.
        from songselector.ui.similarity_map import MIN_INFO_WIDTH, Card, MapLabel
        name = 'LA_PHAZE_VS_MADNESS_ONE_STEP_BEYOND_REMIX_Free_Mp3_Download_a_a_www.mrtzcmp3.net'
        dot = self.map.dots[self.key(5)]
        card = Card('#ffffff', 1)
        card.show_at(dot, '<b>Short</b>', 300)
        short_width, one_line = card.box_size()
        self.assertLess(short_width, 150)  # short text keeps its own width
        card.show_at(dot, f'<b>{name}</b>', 300)
        width, height = card.box_size()
        self.assertLessEqual(width, 300)
        self.assertGreater(height, one_line * 1.5)  # wrapped onto more lines instead
        label = MapLabel()
        label.set_html(f'{name}<br>F minor (4A) at master tempo, 130 BPM', 300)
        self.assertLessEqual(label.box_size()[0], 300)
        self.assertEqual(self.map.info_width(), 360)  # the default
        self.window.settings['Map info width'] = 50
        self.assertEqual(self.map.info_width(), MIN_INFO_WIDTH)
        self.window.settings['Map info width'] = 500
        self.map.hover(self.key(5))
        self.assertLessEqual(self.map.hover_card.box_size()[0], 500)


class SimilarityMapInteractionTests(MapWindowTestBase):
    """Selection details, previewing matches, dragging files out, sorting."""

    def matches(self):
        tree = self.map.suggestions
        return [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]

    def set_match_filter(self, name):
        self.map.match_filter.setCurrentIndex(self.map.match_filter.findData(name))

    def set_edges(self, *names):
        for name, action in self.map.edge_actions.items():
            action.setChecked(name in names)

    def matched_keys(self):
        return {item.data(0, 0x0100) for item in self.matches()}

    def test_closest_matches_can_follow_the_edges_selection(self):
        # Asked 2026-11-17: list only the relations checked under Edges. Keys and colours both follow index % 3.
        self.set_match_filter('all')
        self.map.select(self.key(1))
        self.assertEqual(len(self.matches()), 23)  # every other analysed track
        self.set_edges('perfect_mix')
        self.set_match_filter('edges')
        same_group = {self.key(i) for i in range(24) if i % 3 == 1 and i != 1}
        self.assertEqual(self.matched_keys(), same_group)
        self.assertEqual({item.text(1) for item in self.matches()}, {'Perfect mix'})
        self.set_edges('energy_boost')  # nothing here is an energy boost of track 1: the list follows the menu
        self.assertEqual(self.matched_keys(), set())
        self.set_edges(EDGE_SAME_COLOR)
        self.assertEqual(self.matched_keys(), same_group)
        self.assertEqual(self.window.settings['Map match filter'], 'edges')

    def test_old_harmonic_only_setting_carries_over(self):
        from songselector.ui.similarity_map import SimilarityMapWidget
        widget = SimilarityMapWidget(self.map.store, {'Map harmonic only': True})
        self.assertEqual(widget.match_filter.currentData(), 'harmonic')
        widget = SimilarityMapWidget(self.map.store, {'Map harmonic only': False})
        self.assertEqual(widget.match_filter.currentData(), 'all')

    def test_ctrl_click_on_empty_space_ends_the_comparison(self):
        from PyQt5.QtCore import QPoint, Qt
        from PyQt5.QtTest import QTest

        from songselector.ui.similarity_map import DotItem
        self.window.resize(1400, 900)
        self.window.show()
        self.application.processEvents()
        self.map.select(self.key(0))
        self.map.compare(self.key(3))
        view = self.map.view
        empty = QPoint(3, 3)
        self.assertFalse(any(isinstance(item, DotItem) for item in view.items(empty)))
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.ControlModifier, empty)
        self.application.processEvents()
        self.assertIsNone(self.map.preview_key)
        self.assertFalse(self.map.preview_card.isVisible())
        self.assertEqual(self.map.selected_key, self.key(0))  # the selection stays

    def test_the_map_can_be_dragged_anywhere_and_fit_brings_it_back(self):
        # Reported 2026-11-20: the map could hardly be moved (a view scrolls only within its scene rect, which was
        # the dots plus 5 %), so a hover card at the edge stayed cut off. Dragging stands in for the scroll bars.
        self.window.resize(1400, 900)
        self.window.show()
        self.application.processEvents()
        self.map.fit()
        view = self.map.view
        dots = self.map._dots_rect()
        shown = lambda: view.mapToScene(view.viewport().rect()).boundingRect()  # noqa: E731
        self.assertTrue(shown().intersects(dots))
        for bar in (view.horizontalScrollBar(), view.verticalScrollBar()):
            bar.setValue(bar.maximum())  # as far right and down as a drag goes
        self.assertFalse(shown().intersects(dots))  # the dots can leave the view entirely
        view.scale(0.5, 0.5)  # zoomed out, it still moves
        bar = view.horizontalScrollBar()
        self.assertGreater(bar.maximum() - bar.minimum(), 0)
        self.map.fit()
        self.assertTrue(shown().contains(dots.center()))

    def test_label_and_cards_never_overlap(self):
        # Asked 2026-11-17. Zoomed far out, the selected, compared and hovered dots lie on nearly the same pixel:
        # the label and both cards used to be drawn on top of each other.
        from PyQt5.QtWidgets import QGraphicsRectItem

        from songselector.core.placement import overlap
        self.window.resize(1400, 900)
        self.window.show()
        self.application.processEvents()
        view = self.map.view
        view.resetTransform()
        view.scale(0.001, 0.001)
        view.centerOn(self.map.dots[self.key(0)])
        self.map.select(self.key(0))
        self.map.compare(self.key(3))
        self.map.hover(self.key(6))
        boxes = (self.map.label, self.map.preview_card, self.map.hover_card)
        self.assertTrue(all(box.isVisible() for box in boxes))

        def pixel_rect(box):
            point = view.mapFromScene(box.pos())
            local = box.rect() if isinstance(box, QGraphicsRectItem) else box.path().boundingRect()
            return point.x() + local.x(), point.y() + local.y(), local.width(), local.height()

        rects = [pixel_rect(box) for box in boxes]
        for first in range(3):
            for second in range(first + 1, 3):
                self.assertEqual(overlap(rects[first], rects[second]), 0, (boxes[first], boxes[second]))

    def test_click_on_a_match_highlights_it_double_click_selects_it(self):
        from PyQt5.QtCore import QPoint, Qt
        from PyQt5.QtTest import QTest
        self.window.resize(1400, 900)
        self.window.show()
        self.application.processEvents()
        self.map.select(self.key(0))
        tree = self.map.suggestions
        first = self.matches()[0]
        match = first.data(0, 0x0100)
        row = tree.visualItemRect(first)  # the row is wider than the list (scrolls): click inside the visible part
        QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=QPoint(20, row.center().y()))
        self.application.processEvents()
        self.assertEqual(self.map.selected_key, self.key(0))  # the selection stays
        self.assertEqual(self.map.preview_key, match)
        self.assertEqual(self.map.dots[match].pen().color().name(), '#ff2bd6')
        self.assertTrue(self.map.preview_glow.isVisible())
        self.assertEqual(self.map.preview_glow.pos(), self.map.dots[match].pos())
        self.assertEqual(self.map.selected_glow.pos(), self.map.dots[self.key(0)].pos())
        self.assertEqual([item.data(0, 0x0100) for item in self.matches()][0], match)  # list unchanged
        QTest.mouseDClick(tree.viewport(), Qt.LeftButton, pos=QPoint(20, tree.visualItemRect(first).center().y()))
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
        # solid edges only: the dashed line to a clicked match is opaque
        def alphas():
            return {item.pen().color().alpha() for item in self.map.edge_items if item.pen().style() == 1}
        self.assertEqual(max(alphas()), 170)  # the selected track's strongest edges
        self.assertNotIn(85, alphas())
        other_key_group = next(item.data(0, 0x0100) for item in self.matches()
                               if int(item.data(0, 0x0100).split('track')[-1].split('.')[0]) % 3 == 1)
        self.map.preview(other_key_group)
        self.assertIn(85, alphas())  # the clicked match's strongest edges: half of 170
        self.assertEqual(max(alphas()), 170)
        self.set_match_filter('harmonic')  # the list is rebuilt: highlight and pale edges go
        self.assertIsNone(self.map.preview_key)
        self.assertNotIn(85, alphas())

    def test_escape_ends_the_comparison_then_the_selection(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        self.window.show()
        self.map.select(self.key(0))
        self.map.compare(self.key(3))
        self.map.view.setFocus()
        self.application.processEvents()
        QTest.keyClick(self.map.view, Qt.Key_Escape)  # first: the compared track goes, the selection stays
        self.application.processEvents()
        self.assertEqual(self.map.selected_key, self.key(0))
        self.assertIsNone(self.map.preview_key)
        self.assertFalse(self.map.preview_card.isVisible())
        self.assertGreater(self.map.suggestions.topLevelItemCount(), 0)
        QTest.keyClick(self.map.view, Qt.Key_Escape)  # then the selection
        self.application.processEvents()
        self.assertIsNone(self.map.selected_key)
        self.assertIsNone(self.map.preview_key)
        self.assertEqual(self.map.suggestions.topLevelItemCount(), 0)
        self.assertEqual(self.map.match_keys, [])
        self.assertFalse(self.map.selected_glow.isVisible())

    def test_ctrl_click_compares_a_dot_with_the_selected_track(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        self.window.resize(1400, 900)
        self.window.show()
        self.application.processEvents()
        self.map.select(self.key(0))
        other = self.key(3)  # same tempo-adjusted key as track 0, same style
        view = self.map.view
        view.centerOn(self.map.dots[other])
        self.application.processEvents()
        point = view.mapFromScene(self.map.dots[other].pos())
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.ControlModifier, point)
        self.application.processEvents()
        self.assertEqual(self.map.selected_key, self.key(0))  # the base track stays selected
        self.assertEqual(self.map.preview_key, other)
        self.assertTrue(self.map.preview_glow.isVisible())
        card = self.map.preview_card.text.toPlainText()
        self.assertTrue(self.map.preview_card.isVisible())
        self.assertIn('breaks 3', card)
        self.assertIn('Perfect mix', card)
        mix, similarity = self.map.relation(other)
        self.assertEqual(mix.name, 'perfect_mix')
        self.assertIn(f'{similarity * 100:.0f} % similar', card)
        self.assertEqual(self.map.suggestions.currentItem().data(0, 0x0100), other)  # its row is marked
        dashed = [item for item in self.map.edge_items if item.pen().style() == Qt.DashLine]
        self.assertEqual(len(dashed), 1)  # the line to the base track, in the perfect-mix colour
        self.assertEqual(dashed[0].pen().color().name(), '#4cd964')
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.ControlModifier, point)  # again: ends it
        self.application.processEvents()
        self.assertIsNone(self.map.preview_key)
        self.assertFalse(self.map.preview_card.isVisible())
        self.assertFalse([item for item in self.map.edge_items if item.pen().style() == Qt.DashLine])
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, point)  # a plain click selects
        self.application.processEvents()
        self.assertEqual(self.map.selected_key, other)

    def test_clicked_match_gets_a_card_with_mix_and_similarity(self):
        self.map.select(self.key(0))
        match = self.matches()[0]
        self.map.preview(match.data(0, 0x0100))
        card = self.map.preview_card.text.toPlainText()
        self.assertIn(match.text(0), card.replace(' % similar', ' %'))  # same score as the list
        self.map.select(self.key(13))
        self.assertFalse(self.map.preview_card.isVisible())

    def test_matches_on_the_playlist_are_italic(self):
        self.map.request_add_to_playlist.emit(self.key(1))
        self.map.select(self.key(0))
        italic = {item.data(0, 0x0100) for item in self.matches() if item.font(0).italic()}
        self.assertEqual(italic, {self.key(1)})

    def test_harmonic_only_keeps_tracks_without_a_key(self):
        self.set_match_filter('harmonic')
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
        self.assertIn('Group ', self.map.card_html(self.key(0)))
        self.assertEqual(self.window.settings['Map grouping'], 'kmeans')
        self.assertEqual(self.window.settings['Map grouping parameters']['kmeans'], 2)
        self.map.grouping.setCurrentIndex(0)
        self.assertEqual({key: dot.brush().color().name() for key, dot in self.map.dots.items()}, traktor)
        self.assertFalse(self.map.grouping_parameter.isVisible())

    def wait_for_map(self):
        """Until the map is loaded, including a pending re-map of a changed List ("Map the List only")."""
        deadline = time.monotonic() + 60
        timer = lambda: getattr(self.map, "_follow_timer", None) is not None and self.map._follow_timer.isActive()  # noqa: E731
        while (self.map._loading or self.map._again or timer()) and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.application.processEvents()

    def test_only_listed_tracks_are_mapped_and_grouped_on_their_own_and_the_library_map_returns(self):
        store = EmbeddingStore(self.root / 'embeddings.sqlite')
        library_layout = store.load_layout()
        self.map.grouping.setCurrentIndex(self.map.grouping.findData('kmeans'))
        self.map.grouping_parameter.setValue(2)
        self.wait_for_groups()
        self.window.search_bar.setText('breaks')
        self.map.only_button.setChecked(True)
        self.wait_for_map()
        self.wait_for_groups()
        self.assertEqual(set(self.map.data.keys), {self.key(i) for i in range(12)})
        self.assertEqual(set(self.map.groups), set(self.map.data.keys))  # grouped among themselves
        self.assertIn('of the 12 mapped tracks', self.map.grouping_summary.text())
        self.assertEqual(store.load_layout(), library_layout)             # the library layout is untouched
        self.assertEqual(self.visible(), set(self.map.data.keys))
        self.window.search_bar.clear()                                     # the map follows the List
        self.wait_for_map()
        self.assertEqual(len(self.map.data.keys), 24)
        self.assertEqual(len(self.visible()), 24)
        self.map.rearrange_button.click()                                  # arranges the List from scratch
        self.wait_for_map()
        self.assertEqual(len(self.map.data.keys), 24)
        self.map.only_button.setChecked(False)
        self.wait_for_map()
        self.wait_for_groups()
        self.assertEqual(len(self.map.data.keys), 24)
        self.assertIn('of all 24 analysed tracks', self.map.grouping_summary.text())
        self.assertEqual(store.load_layout(), library_layout)

    def describe(self, indexes, prompt='dark rolling'):
        """A description search result in the List (as when the text search answers; also after a model switch)."""
        from songselector.core.embedding_models import LAION_CLAP
        self.window._description_model_id = LAION_CLAP.id
        self.window.show_description_results(prompt, [(self.key(i), 0.5 - i / 100) for i in indexes], 0.01)

    def test_map_the_list_only_follows_new_description_searches(self):
        # Reported 2026-11-17: after a new search (or a CLAP model switch, which searches again) the map showed only
        # the tracks that were in both the old and the new List, and the button did not bring the new ones.
        self.assertEqual(self.map.only_button.text(), 'Map the List only')
        self.describe(range(0, 6))
        self.map.only_button.setChecked(True)
        self.wait_for_map()
        self.assertEqual(set(self.map.data.keys), {self.key(i) for i in range(0, 6)})
        self.describe(range(3, 15), prompt='other model, same prompt')
        self.wait_for_map()
        self.assertEqual(set(self.map.data.keys), {self.key(i) for i in range(3, 15)})
        self.assertEqual(self.visible(), {self.key(i) for i in range(3, 15)})
        self.assertIn('only the tracks the List shows', self.map._base_status)

    def test_a_burst_of_list_changes_gives_one_new_map(self):
        from songselector.ui import similarity_map
        self.map.only_button.setChecked(True)
        self.wait_for_map()
        with patch.object(similarity_map, 'build_map_data', wraps=similarity_map.build_map_data) as build:
            for text in ('b', 'br', 'bre', 'breaks'):
                self.window.search_bar.setText(text)
            self.wait_for_map()
        self.assertEqual(build.call_count, 1)
        self.assertEqual(set(self.map.data.keys), {self.key(i) for i in range(12)})

    def test_a_list_change_during_a_load_maps_the_latest_list(self):
        self.map.only_button.setChecked(True)  # starts a load in the background
        self.assertTrue(self.map._loading)
        self.window.search_bar.setText('dnb')
        self.map._follow_timer.stop()
        self.map._follow_list()                # the pause is over while the first load still runs
        self.assertTrue(self.map._again)
        self.wait_for_map()
        self.assertEqual(set(self.map.data.keys), {self.key(i) for i in range(12, 24)})

    def test_an_unchanged_list_does_not_map_again(self):
        from songselector.ui import similarity_map
        self.window.search_bar.setText('breaks')
        self.map.only_button.setChecked(True)
        self.wait_for_map()
        with patch.object(similarity_map, 'build_map_data', wraps=similarity_map.build_map_data) as build:
            self.window.filter_items()                 # filtered again: same rows
            self.window.apply_tempo()     # the tempo moved: same rows, new texts
            self.wait_for_map()
        build.assert_not_called()

    def test_the_map_spinner_turns_while_arranging_and_grouping(self):
        spinner = self.map.spinner
        self.assertFalse(spinner.busy())
        self.map.load(rearrange=True)
        self.assertEqual(spinner.reasons(), ['Arranging the map'])
        self.wait_for_map()
        self.assertFalse(spinner.busy())
        self.map.grouping.setCurrentIndex(self.map.grouping.findData('kmeans'))
        self.assertIn('Grouping', spinner.reasons())
        self.wait_for_groups()
        self.assertFalse(spinner.busy())
        self.map.grouping.setCurrentIndex(0)  # off
        self.assertFalse(spinner.busy())

    def test_every_grouping_method_runs_on_the_map(self):
        for method in ('kmeans', 'communities', 'density'):
            self.map.grouping.setCurrentIndex(self.map.grouping.findData(method))
            self.wait_for_groups()
            self.assertEqual(set(self.map.groups), set(self.map.data.keys), method)
            self.assertIn('groups of all 24', self.map.grouping_summary.text(), method)

    def test_selected_track_shows_details_box_and_label_on_the_map(self):
        self.map.select(self.key(4))
        self.assertTrue(self.map.label.isVisible())
        self.assertIn('breaks artist - breaks 4', self.map.label_text.toPlainText())
        self.assertIn('master tempo', self.map.label_text.toPlainText())
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
        with patch('songselector.ui.similarity_map.QDrag.exec_',
                   lambda drag, *args: dragged.append(drag.mimeData().urls()) or 1):
            self.map.drag_files([self.key(3)])
        self.assertEqual(Path(dragged[0][0].toLocalFile()), self.root / 'track3.mp3')

    def test_edge_cap_message_disappears_when_no_longer_true(self):
        with patch('songselector.ui.similarity_map.MAX_EDGES', 5):
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
        from songselector.ui.similarity_map import DEFAULT_MATCH_COLUMNS, MATCH_COLUMNS
        tree = self.map.suggestions
        shown = [name for column, name in enumerate(MATCH_COLUMNS) if not tree.isColumnHidden(column)]
        self.assertEqual(shown, DEFAULT_MATCH_COLUMNS)
        bpm, color = MATCH_COLUMNS.index('Original BPM'), MATCH_COLUMNS.index('Color')
        tree.show_column(bpm, True)
        tree.show_column(color, True)
        tree.show_column(MATCH_COLUMNS.index('Mix'), False)
        self.assertEqual(self.window.settings['Map match columns'],
                         ['Similarity', 'Artist', 'Title', 'Original BPM', 'Color', 'Cover'])
        self.map.select(self.key(0))
        self.assertEqual(self.matches()[0].text(bpm), '128')
        self.assertEqual(self.matches()[0].data(bpm, 0x0102), 128.0)
        tree.sortByColumn(color, 0)  # Qt.AscendingOrder: by colour number
        colours = [int(item.text(color)) for item in self.matches()]
        self.assertEqual(colours, sorted(colours))
        rating = MATCH_COLUMNS.index('Rating')
        delegate = tree.itemDelegateForColumn(rating)
        self.assertEqual(delegate.displayText('3', None), '★★★☆☆')

    def test_edges_are_curved_unless_switched_to_straight(self):
        for name, action in self.map.edge_actions.items():
            action.setChecked(name == 'perfect_mix')
        self.map.select(self.key(0))
        def paths():
            return [item.path() for item in self.map.edge_items]
        self.assertTrue(all(path.elementCount() % 4 == 0 for path in paths()))  # move + curve (3 elements)
        start, end = paths()[0].elementAt(0), paths()[0].elementAt(3)
        bend = paths()[0].elementAt(1)
        self.assertNotAlmostEqual((bend.x - start.x) * (end.y - start.y), (bend.y - start.y) * (end.x - start.x), 1)
        self.map.curved_action.setChecked(False)
        self.assertTrue(all(path.elementCount() % 2 == 0 and path.elementAt(1).isLineTo() for path in paths()))
        self.assertFalse(self.window.settings['Map curved edges'])

    def test_3d_view_turns_with_shift_drag_and_2d_comes_back(self):
        from PyQt5.QtCore import QPoint, Qt
        from PyQt5.QtTest import QTest
        flat = {key: dot.pos() for key, dot in self.map.dots.items()}
        self.map.select(self.key(0))
        self.map.view_3d_button.setChecked(True)  # first time: arranged in the background
        self.wait_for_map()
        self.assertTrue(self.map.showing_3d())
        self.assertEqual(len(next(iter(self.map.data.positions3d.values()))), 3)
        self.assertEqual(len(EmbeddingStore(self.root / 'embeddings.sqlite').load_layout_3d()), 24)  # cached
        self.assertTrue(self.window.settings['Map 3D'])
        opacities = {round(dot.opacity(), 2) for dot in self.map.dots.values()}
        self.assertGreater(len(opacities), 5)  # far dots fade
        depth = self.map._depth
        near, far = max(depth, key=depth.get), min(depth, key=depth.get)
        near_size, far_size = self.map.dots[near].scale(), self.map.dots[far].scale()
        self.assertGreater(near_size, 1.5 * far_size)  # and are drawn smaller than near ones
        self.assertTrue(0.5 <= far_size < 1 < near_size <= 1.6)
        before = {key: dot.pos() for key, dot in self.map.dots.items()}
        self.window.resize(1400, 900)
        self.window.show()
        self.application.processEvents()
        viewport = self.map.view.viewport()
        QTest.mousePress(viewport, Qt.LeftButton, Qt.ShiftModifier, QPoint(200, 200))
        from PyQt5.QtCore import QEvent
        from PyQt5.QtGui import QMouseEvent
        from PyQt5.QtWidgets import QApplication
        QApplication.sendEvent(viewport, QMouseEvent(QEvent.MouseMove, QPoint(260, 230), Qt.NoButton,
                                                     Qt.LeftButton, Qt.ShiftModifier))  # QTest.mouseMove: no event offscreen
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.ShiftModifier, QPoint(260, 230))
        self.application.processEvents()
        self.assertNotEqual(self.map.angles, (0.6, -0.35))
        self.assertEqual(self.window.settings['Map 3D angles'], list(self.map.angles))
        self.assertEqual(self.map.selected_key, self.key(0))  # rotating selects nothing
        moved = sum(dot.pos() != before[key] for key, dot in self.map.dots.items())
        self.assertEqual(moved, 24)
        self.assertEqual(self.map.selected_glow.pos(), self.map.dots[self.key(0)].pos())  # the glow follows
        self.map.view_3d_button.setChecked(False)
        self.assertEqual({key: dot.pos() for key, dot in self.map.dots.items()}, flat)
        self.assertEqual({dot.opacity() for dot in self.map.dots.values()}, {1.0})
        self.assertEqual({dot.scale() for dot in self.map.dots.values()}, {1.0})


class MapViewOptionsTests(MapWindowTestBase):
    """Asked 2026-11-20: turn the 2D map, choose every detail the map shows and where, hide the details panel, the
    map's buttons below it, the search rows folded away."""

    def show_window(self):
        self.window.resize(1400, 900)
        self.window.show()
        self.application.processEvents()

    def wait_for(self, condition, seconds=30):
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.02)
        self.application.processEvents()

    def test_shift_right_drag_turns_the_2d_map_about_the_middle_of_the_view(self):
        from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
        from PyQt5.QtGui import QContextMenuEvent, QMouseEvent
        from PyQt5.QtWidgets import QApplication, QGraphicsView

        from songselector.ui.similarity_map import ROTATE_SPEED
        self.show_window()
        view, viewport = self.map.view, self.map.view.viewport()
        first, other = self.map.dots[self.key(0)], self.map.dots[self.key(13)]
        before = other.pos() - first.pos()
        view.centerOn(first)
        self.application.processEvents()
        start = view.mapFromScene(first.pos())  # the press lands on a dot: it turns, it does not select or open a menu
        menus = []
        self.map.request_context_menu.connect(lambda key, _pos: menus.append(key))

        def send(kind, right, button, buttons):  # QTest.mouseMove sends no event offscreen
            event = QMouseEvent(kind, QPointF(start + QPoint(right, 0)), button, buttons, Qt.ShiftModifier)
            QApplication.sendEvent(viewport, event)
        send(QEvent.MouseButtonPress, 0, Qt.RightButton, Qt.RightButton)
        send(QEvent.MouseMove, 60, Qt.NoButton, Qt.RightButton)
        send(QEvent.MouseMove, 100, Qt.NoButton, Qt.RightButton)
        send(QEvent.MouseButtonRelease, 100, Qt.RightButton, Qt.NoButton)
        self.application.processEvents()  # the moves are drawn once
        angle = 100 * ROTATE_SPEED          # to the right: clockwise
        self.assertAlmostEqual(self.map.turn_angle, angle)
        self.assertAlmostEqual(self.window.settings['Map 2D turn'], angle)
        after = other.pos() - first.pos()
        cos, sin = np.cos(angle), np.sin(angle)
        self.assertAlmostEqual(after.x(), before.x() * cos - before.y() * sin, places=3)  # y points down: clockwise
        self.assertAlmostEqual(after.y(), before.x() * sin + before.y() * cos, places=3)
        self.assertLessEqual((view.mapFromScene(first.pos()) - start).manhattanLength(), 2)  # the middle stays
        self.assertIsNone(self.map.selected_key)
        self.assertEqual(menus, [])
        with patch.object(QGraphicsView, 'contextMenuEvent') as base:
            QApplication.sendEvent(viewport, QContextMenuEvent(QContextMenuEvent.Mouse, start))
            base.assert_not_called()   # the context menu event of the turn's right button
            QApplication.sendEvent(viewport, QContextMenuEvent(QContextMenuEvent.Mouse, start))
            base.assert_called_once()  # a later right-click goes on as before
        self.map.fit()  # fits the turned map: the dots keep their turned positions
        self.assertAlmostEqual((other.pos() - first.pos()).x(), after.x(), places=3)

    def test_every_detail_can_be_switched_off_in_each_place(self):
        from songselector.ui.similarity_map import (
            CARD,
            DEFAULT_DETAILS,
            GROUP_ITEM,
            KEY_ITEM,
            LABEL,
            NAME_ITEM,
            PANEL,
            RELATION_ITEM,
        )
        self.map.grouping.setCurrentIndex(self.map.grouping.findData('kmeans'))
        self.wait_for(lambda: bool(self.map.groups))
        self.map.select(self.key(4))
        card = lambda: self.map.hover_card.text.toPlainText()  # noqa: E731
        texts = {NAME_ITEM: 'breaks artist - breaks 5', KEY_ITEM: '128 BPM', RELATION_ITEM: '% similar',
                 GROUP_ITEM: 'Group ', 'Genre': 'Genre'}
        self.map.hover(self.key(5))
        for text in texts.values():
            self.assertIn(text, card())  # the defaults: as before
        for item, text in texts.items():
            self.window.settings['Map details'] = {CARD: [name for name in DEFAULT_DETAILS[CARD] if name != item]}
            self.window._refresh_map()  # as after the dialog
            self.assertNotIn(text, card(), item)
            self.assertTrue(all(other in card() for other in texts.values() if other != text), item)
        # Nothing chosen: no card, no label (the ring and the glow still mark the selected track), an empty panel
        self.window.settings['Map details'] = {CARD: [], LABEL: [], PANEL: []}
        self.window._refresh_map()
        self.assertFalse(self.map.hover_card.isVisible())
        self.assertFalse(self.map.label.isVisible())
        self.assertTrue(self.map.selected_glow.isVisible())
        self.assertEqual(self.map.details.text(), '')
        # Columns on the label too, and only the key line in the panel
        self.window.settings['Map details'] = {CARD: [], LABEL: ['Genre'], PANEL: [KEY_ITEM]}
        self.window._refresh_map()
        self.assertIn('Genre\nbreaks', self.map.label_text.toPlainText())
        self.assertNotIn('master tempo', self.map.label_text.toPlainText())
        self.assertIn('Key now: ', self.map.details.text())
        self.assertNotIn('breaks artist', self.map.details.text())

    def test_hover_columns_chosen_before_carry_over_and_the_dialog_saves_each_place(self):
        from PyQt5.QtWidgets import QDialog

        from songselector.ui.similarity_map import (
            CARD,
            COVER_ITEM,
            DEFAULT_DETAILS,
            GROUP_ITEM,
            KEY_ITEM,
            LABEL,
            NAME_ITEM,
            PANEL,
            RELATION_ITEM,
            detail_items,
        )
        before = {'Map hover fields': ['Original Key']}  # up to 2026-11-20: the columns, card and panel alike
        self.assertEqual(detail_items(before, CARD),
                         [COVER_ITEM, NAME_ITEM, KEY_ITEM, RELATION_ITEM, GROUP_ITEM, 'Original Key'])
        self.assertEqual(detail_items(before, PANEL), [COVER_ITEM, NAME_ITEM, KEY_ITEM, GROUP_ITEM, 'Original Key'])
        self.assertEqual(detail_items(before, LABEL), [NAME_ITEM, KEY_ITEM])
        self.assertEqual(detail_items({}, CARD), DEFAULT_DETAILS[CARD])
        self.window.settings['Map hover fields'] = ['Original Key']
        dialog = self.window.map_details_dialog()
        self.assertTrue(dialog.boxes[CARD, 'Original Key'].isChecked())
        self.assertFalse(dialog.boxes[CARD, 'Genre'].isChecked())
        self.assertNotIn((LABEL, RELATION_ITEM), dialog.boxes)  # the selected track has no mix with itself
        self.assertNotIn((PANEL, RELATION_ITEM), dialog.boxes)
        dialog.boxes[CARD, COVER_ITEM].setChecked(False)
        dialog.boxes[LABEL, 'Genre'].setChecked(True)
        chosen = dialog.selected()
        self.assertEqual(chosen[CARD], [NAME_ITEM, KEY_ITEM, RELATION_ITEM, GROUP_ITEM, 'Original Key'])
        self.assertEqual(chosen[LABEL], [NAME_ITEM, KEY_ITEM, 'Genre'])
        with patch.object(dialog, 'exec_', return_value=QDialog.Accepted), \
                patch.object(self.window, 'map_details_dialog', return_value=dialog):
            self.window.choose_map_details()
        self.assertEqual(self.window.settings['Map details'], chosen)
        self.assertNotIn('Map hover fields', self.window.settings)

    def test_speed_change_can_be_chosen_for_the_map_details(self):
        from songselector.config import SPEED_COLUMN
        from songselector.ui.similarity_map import CARD, DEFAULT_DETAILS, LABEL, PANEL
        dialog = self.window.map_details_dialog()
        bpm = dialog.items.index('Original BPM')
        self.assertEqual(dialog.items[bpm + 1], SPEED_COLUMN)  # next to the BPM it comes from, as in the List
        self.assertTrue(all((place, SPEED_COLUMN) in dialog.boxes for place in (CARD, LABEL, PANEL)))
        self.assertFalse(dialog.boxes[CARD, SPEED_COLUMN].isChecked())  # not shown by default
        dialog.boxes[CARD, SPEED_COLUMN].setChecked(True)
        self.assertIn(SPEED_COLUMN, dialog.selected()[CARD])
        self.window.settings['Map details'] = {CARD: DEFAULT_DETAILS[CARD] + [SPEED_COLUMN]}
        self.window._refresh_map()
        self.map.hover(self.key(5))
        speed = self.window._fields_for_key(self.key(5))[SPEED_COLUMN]
        self.assertTrue(speed.endswith('%'))
        self.assertIn(f'{SPEED_COLUMN}\n{speed}', self.map.hover_card.text.toPlainText())

    def test_the_details_panel_hides_by_right_click_beside_the_map_or_the_view_menu(self):
        from PyQt5.QtCore import QPoint
        from PyQt5.QtGui import QContextMenuEvent
        from PyQt5.QtWidgets import QApplication, QMenu

        from songselector.ui.similarity_map import SimilarityMapWidget
        details, action = self.map.details, self.window.map_details_action
        self.assertTrue(action.isChecked())
        self.assertTrue(details.isVisibleTo(self.map))
        self.map.select(self.key(0))
        menus, chosen = [], []

        def show(menu, *_args):
            menus.append([entry.text() for entry in menu.actions()])
            if chosen:
                next(entry for entry in menu.actions() if entry.text() == chosen[0]).trigger()
        chosen.append('Show selected track details')
        with patch.object(QMenu, 'exec_', show):
            # a right-click on a closest match's row: the list passes it on to the panel beside the map
            QApplication.sendEvent(self.map.suggestions.viewport(), QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(5, 5)))
        self.assertEqual(menus[-1], ['Show selected track details', 'Choose track details...'])
        self.assertFalse(details.isVisibleTo(self.map))
        self.assertFalse(action.isChecked())  # the View menu follows
        self.assertFalse(self.window.settings['Map details panel'])
        self.assertTrue(SimilarityMapWidget(self.map.store, {'Map details panel': False}).details.isHidden())  # kept
        action.setChecked(True)  # View -> Selected track details
        self.assertTrue(details.isVisibleTo(self.map))
        self.assertTrue(self.window.settings['Map details panel'])
        requested = []
        self.map.details_dialog_requested.connect(lambda: requested.append(True))
        chosen[:] = ['Choose track details...']
        details.setSelection(0, 4)
        from PyQt5.QtWidgets import QDialog

        from songselector.ui.map_settings_dialog import MapDetailsDialog
        with patch.object(QMenu, 'exec_', show), patch.object(MapDetailsDialog, 'exec_', return_value=QDialog.Rejected):
            self.map._side_menu(details, QPoint(1, 1))  # "Choose track details..." opens View -> Map track details...
        self.assertIn('Copy', menus[-1])  # selected details text can still be copied
        self.assertEqual(requested, [True])

    def test_the_search_rows_fold_away_and_come_back(self):
        from songselector.ui.main_window import MainWindow
        self.show_window()
        splitter, panel, action = self.window.search_splitter, self.window.search_panel, self.window.search_bars_action
        self.assertTrue(action.isChecked())
        self.assertEqual(splitter.sizes()[0], panel.sizeHint().height())  # the rows whole, never stretched
        action.setChecked(False)  # View -> Search bars
        self.assertEqual(splitter.sizes()[0], 0)
        self.assertFalse(self.window.settings['Show search bars'])
        action.setChecked(True)
        self.assertEqual(splitter.sizes()[0], panel.sizeHint().height())
        splitter.moveSplitter(0, 1)  # dragging the line up folds them away too, as on the left; the menu follows
        self.assertEqual(splitter.sizes()[0], 0)
        self.assertFalse(action.isChecked())
        self.window.close()  # saves the settings: the next start begins without the rows
        self.application.processEvents()
        self.window = MainWindow()
        self.map = self.window.similarity_map
        self.show_window()
        self.assertEqual(self.window.search_splitter.sizes()[0], 0)
        self.assertFalse(self.window.search_bars_action.isChecked())


class TurnTests(unittest.TestCase):
    def test_points_turn_clockwise_on_screen(self):
        import math

        from songselector.ui.similarity_map import turned
        np.testing.assert_allclose(turned([(1, 0), (0, 1)], math.pi / 2), [(0, 1), (-1, 0)], atol=1e-12)  # right -> down
        np.testing.assert_allclose(turned([(3, 4)], 0), [(3, 4)])


class ShownFieldsTests(unittest.TestCase):
    def test_empty_values_and_colour_zero_are_not_shown(self):
        from songselector.ui.similarity_map import shown_fields
        fields = {'Artist': 'A', 'Genre': '', 'Color': '0', 'Color - Song Selector': '5', 'Rating': '0',
                  'Rating - Song Selector': '4'}
        names = ['Artist', 'Genre', 'Color', 'Color - Song Selector', 'Rating', 'Rating - Song Selector', 'Comment']
        self.assertEqual(shown_fields(fields, names),
                         [('Artist', 'A'), ('Color - Song Selector', '5'), ('Rating - Song Selector', '★★★★☆')])


class FieldHtmlTests(unittest.TestCase):
    def test_colours_are_shown_as_a_coloured_dot_and_name(self):
        from songselector.ui.similarity_map import field_html
        self.assertEqual(field_html('Color', '2'), '<span style="color:#ffa500">&#9679;</span> Orange')
        self.assertEqual(field_html('Color - Song Selector', '5'), '<span style="color:#0000ff">&#9679;</span> Blue')
        self.assertEqual(field_html('Color', 'x'), 'x')
        self.assertEqual(field_html('Title', 'A & B'), 'A &amp; B')


class MapWindowTests(MapWindowTestBase):
    """Asked 2026-11-17: the map in a window of its own (easier to resize and move, e.g. to a second screen)."""

    def test_own_window_and_back_to_the_tab(self):
        from songselector.ui.map_window import MapPlaceholder
        self.window.show()
        self.map.detach_button.click()
        self.application.processEvents()
        window = self.window.map_window
        self.assertIsNotNone(window)
        self.assertIs(self.map.window(), window)
        self.assertTrue(window.isVisible())
        self.assertIsInstance(self.window.library_tabs.widget(1), MapPlaceholder)
        self.assertTrue(self.window.map_visible())
        self.assertEqual(self.map.detach_button.text(), 'Back to the tab')
        self.assertTrue(self.window.settings['Map detached'])
        self.window.search_bar.setText('dnb')  # the map keeps following the List
        self.assertEqual(self.visible(), {self.key(i) for i in range(12, 24)})
        window.close()                          # closing the window docks the map again
        self.application.processEvents()
        self.assertIsNone(self.window.map_window)
        self.assertIs(self.window.library_tabs.widget(1), self.map)
        self.assertFalse(self.map.detach_button.isChecked())
        self.assertFalse(self.window.settings['Map detached'])

    def test_window_geometry_and_state_are_remembered(self):
        self.window.show()
        self.window.set_map_detached(True)
        # A size the window can take (its minimum depends on the fonts; the offscreen test platform's are wide).
        width = max(640, self.window.map_window.minimumSizeHint().width() + 50)
        self.window.map_window.resize(width, 480)
        self.application.processEvents()
        self.window.set_map_detached(False)
        self.assertIn('Map window geometry', self.window.settings)
        self.window.set_map_detached(True)
        self.application.processEvents()
        self.assertEqual(self.window.map_window.size().width(), width)
        # Closing the app with the map detached: since 2026-11-20 (no "Own window" button any more) it opens docked
        # next time, as there would be no button to bring it back.
        self.window.close()
        self.application.processEvents()
        self.assertTrue(self.window.settings['Map detached'])
        from songselector.ui.main_window import MainWindow
        restarted = MainWindow()
        try:
            self.application.processEvents()
            self.assertIsNone(restarted.map_window)
            self.assertFalse(restarted.settings['Map detached'])
        finally:
            restarted.close()
            self.application.processEvents()

    def test_the_map_window_can_be_much_narrower_than_the_main_window(self):
        # One row of all the map's controls used to make the map at least the whole row wide; since 2026-11-20 the
        # toolbar folds what does not fit into its >> menu, so the map can be narrower than its controls.
        self.window.show()
        self.window.set_map_detached(True)
        self.application.processEvents()
        toolbar = self.map.toolbar
        controls = [toolbar.widgetForAction(action) for action in toolbar.actions()]
        one_row = sum(widget.minimumSizeHint().width() for widget in controls if widget is not None)
        self.assertLess(self.map.minimumSizeHint().width(), 0.75 * one_row)

    def test_detaching_while_the_list_tab_is_current_shows_the_map(self):
        # Reported 2026-11-17: the map's own window was grey. Qt hides the tab pages that are not current, and the
        # map stayed hidden in its new window (e.g. when the app starts with the map detached).
        self.window.show()
        self.window.library_tabs.setCurrentIndex(0)
        self.application.processEvents()
        self.assertFalse(self.map.isVisible())
        self.window.set_map_detached(True)
        self.application.processEvents()
        self.assertTrue(self.map.isVisible())
        self.assertTrue(self.map.view.isVisible())
        self.window.set_map_detached(False)  # back in its tab (not the current one): hidden there, as tabs are
        self.window.library_tabs.setCurrentIndex(1)
        self.application.processEvents()
        self.assertTrue(self.map.isVisible())

    def test_ctrl_2_brings_the_detached_map_to_the_front(self):
        self.window.show()
        self.window.set_map_detached(True)
        with patch.object(self.window.map_window, 'raise_') as raised:
            self.window.show_map()
        raised.assert_called_once()
        self.window.set_map_detached(False)
        self.window.library_tabs.setCurrentIndex(0)
        self.window.show_map()
        self.assertIs(self.window.library_tabs.currentWidget(), self.map)


class MapCoverTests(MapWindowTestBase):
    """Asked 2026-11-17: cover art in the map's cards and its closest matches, when a track has one."""

    def setUp(self):
        super().setUp()
        from test_cover_art import add_pictures, image_bytes
        from test_imports import tagged_file
        for index in (0, 3):  # two tracks with a cover; the others have no file at all
            add_pictures(tagged_file(self.root / f'track{index}.mp3'), (3, image_bytes('red')))
        self.path = lambda index: str(self.root / f'track{index}.mp3')

    def wait_for_cover(self, index):
        deadline = time.monotonic() + 10
        while not self.window.covers.known(self.path(index)) and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.application.processEvents()

    def test_cards_and_details_show_the_cover_once_it_is_loaded(self):
        self.map.hover(self.key(0))
        self.assertNotIn('<img', self.map.card_html(self.key(0)).split('<b>')[0])  # requested, not there yet
        self.wait_for_cover(0)
        self.assertIn('<img', self.map.hover_card.text.toHtml())  # the open card was drawn again
        self.map.select(self.key(0))
        self.assertIn('<img', self.map.details.text())
        self.map.hover(self.key(1))                                # no cover: no picture
        self.assertNotIn('<img', self.map.hover_card.text.toHtml())
        # Asked 2026-11-20: the cover can be switched off, for each place on its own
        from songselector.ui.similarity_map import CARD, COVER_ITEM, DEFAULT_DETAILS, LABEL, NAME_ITEM, PANEL
        self.window.settings['Map details'] = {CARD: [item for item in DEFAULT_DETAILS[CARD] if item != COVER_ITEM],
                                               LABEL: [COVER_ITEM, NAME_ITEM], PANEL: DEFAULT_DETAILS[PANEL]}
        self.window._refresh_map()
        self.map.hover(self.key(0))
        self.assertTrue(self.map.hover_card.isVisible())
        self.assertNotIn('<img', self.map.hover_card.text.toHtml())
        self.assertIn('<img', self.map.label_text.toHtml())
        self.assertIn('<img', self.map.details.text())

    def test_closest_matches_have_a_cover_column(self):
        # Reported 2026-11-17: covers as icons in the first column looked messy; they get a column of their own.
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QColor

        from songselector.ui.similarity_map import MATCH_COVER_COLUMN
        tree = self.map.suggestions
        self.window.resize(1400, 900)
        self.window.show()
        self.map.select(self.key(6))  # same style and key group as tracks 0 and 3
        self.wait_for_cover(0)
        self.application.processEvents()
        self.assertFalse(tree.isColumnHidden(MATCH_COVER_COLUMN))
        self.assertEqual(tree.header().visualIndex(MATCH_COVER_COLUMN), 0)  # first on screen
        items = {tree.topLevelItem(i).data(0, Qt.UserRole): tree.topLevelItem(i) for i in range(tree.topLevelItemCount())}
        self.assertTrue(all(item.icon(0).isNull() for item in items.values()))  # no icons next to the similarity
        tree.scrollToItem(items[self.key(0)])
        self.application.processEvents()
        cell = tree.visualRect(tree.indexFromItem(items[self.key(0)], MATCH_COVER_COLUMN))
        self.assertEqual(QColor(tree.viewport().grab().toImage().pixel(cell.center())).name(), '#ff0000')

    def test_an_old_match_column_choice_gets_the_cover_column_once(self):
        from songselector.ui.similarity_map import MATCH_COVER_COLUMN, MatchList
        settings = {'Map match columns': ['Similarity', 'Artist']}
        tree = MatchList(settings)
        self.assertFalse(tree.isColumnHidden(MATCH_COVER_COLUMN))
        self.assertEqual(settings['Map match columns'], ['Similarity', 'Artist', 'Cover'])
        tree.show_column(MATCH_COVER_COLUMN, False)  # hidden on purpose: stays hidden
        self.assertTrue(MatchList(settings).isColumnHidden(MATCH_COVER_COLUMN))


class MapDataPlaceTests(unittest.TestCase):
    def test_a_placed_track_lands_among_its_own_style_in_the_same_vector_space(self):
        from songselector.core.similarity import centred_unit, raw_vectors
        from songselector.ui.similarity_map import MapData
        matrices = two_styles(per_style=10)
        mapped = matrices[:9] + matrices[10:19]   # one track of each style held back
        keys = [f'k{index}' for index in range(len(mapped))]
        vectors, centre = track_vectors(mapped, with_centre=True)
        points = tsne_layout(vectors, iterations=400)
        data = MapData(list(keys), vectors, {key: tuple(point) for key, point in zip(keys, points)}, {}, centre)
        self.assertEqual(data.place({'new0': matrices[9], 'new1': matrices[19], 'k0': matrices[0]}), ['new0', 'new1'])
        self.assertEqual(len(data.vectors), 20)
        np.testing.assert_allclose(data.vectors[data.row['new1']],
                                   centred_unit(raw_vectors([matrices[19]]), centre)[0], rtol=1e-5)
        styles = (range(0, 9), range(9, 18))
        for new, own, other in (('new0', *styles), ('new1', *styles[::-1])):
            row = data.row[new]
            similar = [data.keys[index] for index, _score in nearest(data.vectors, row, count=5, among=range(18))]
            self.assertTrue(all(int(key[1:]) in own for key in similar), (new, similar))  # same vector space
            centroid = lambda indexes: np.mean([data.positions[f'k{i}'] for i in indexes], axis=0)  # noqa: E731
            position = np.array(data.positions[new])
            self.assertLess(np.linalg.norm(position - centroid(own)), np.linalg.norm(position - centroid(other)))


class PlaylistOnMapTests(MapWindowTestBase):
    """Asked 2026-11-17: tracks selected in the Playlist are shown on the map, also when the List filters them out."""

    def wait_for_map(self):
        deadline = time.monotonic() + 60
        timer = lambda: self.map._follow_timer is not None and self.map._follow_timer.isActive()  # noqa: E731
        while (self.map._loading or self.map._again or timer()) and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.application.processEvents()

    def add_to_playlist(self, *indexes):
        for index in indexes:
            self.map.request_add_to_playlist.emit(self.key(index))

    def select_in_playlist(self, *indexes):
        from PyQt5.QtCore import QItemSelectionModel
        tree = self.window.playlist_tree
        tree.clearSelection()
        wanted = {self.key(index) for index in indexes}
        for row in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(row)
            if canonical_path(item.text(self.path_column())) in wanted:
                tree.selectionModel().select(tree.indexFromItem(item), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self.application.processEvents()

    def path_column(self):
        from songselector.config import HEADER_INDEX
        return HEADER_INDEX['Path']

    def pen(self, index):
        return self.map.dots[self.key(index)].pen()

    def test_selected_playlist_tracks_get_an_amber_ring(self):
        self.add_to_playlist(1, 13)
        self.select_in_playlist(1, 13)
        self.assertEqual(set(self.map.highlighted), {self.key(1), self.key(13)})
        for index in (1, 13):
            self.assertEqual(self.pen(index).color().name(), '#ffb000')
            self.assertEqual(self.pen(index).style(), 1)  # solid: the List shows them
        self.assertIn('2 of 2 selected Playlist tracks shown', self.map._base_status)
        self.select_in_playlist()  # nothing selected: the rings go
        self.assertEqual(self.map.highlighted, {})
        self.assertNotEqual(self.pen(1).color().name(), '#ffb000')

    def test_a_playlist_track_the_list_filters_out_is_shown_but_not_matched(self):
        from PyQt5.QtCore import Qt
        self.add_to_playlist(1)
        self.window.search_bar.setText('dnb')       # track 1 is breaks: not in the List
        self.assertNotIn(self.key(1), self.visible())
        self.select_in_playlist(1)
        self.assertIn(self.key(1), self.visible())  # shown anyway
        self.assertEqual(self.pen(1).style(), Qt.DashLine)
        self.assertLess(self.map.dots[self.key(1)].brush().color().alpha(), 255)
        self.map.select(self.key(13))
        matched = {self.map.suggestions.topLevelItem(i).data(0, Qt.UserRole)
                   for i in range(self.map.suggestions.topLevelItemCount())}
        self.assertNotIn(self.key(1), matched)      # not a closest match of a listed track
        self.assertFalse(any(self.key(1) in (source, target) for source, target, *_ in self.map._edges(self.map.criteria())))
        self.map.select(self.key(1))                # its own closest matches come from the List
        matched = {self.map.suggestions.topLevelItem(i).data(0, Qt.UserRole)
                   for i in range(self.map.suggestions.topLevelItemCount())}
        self.assertTrue(matched)
        self.assertTrue(all(int(key.split('track')[-1].split('.')[0]) >= 12 for key in matched))
        self.select_in_playlist()
        self.assertNotIn(self.key(1), self.visible())

    def test_on_a_map_of_the_list_only_a_playlist_track_is_placed_near_similar_tracks(self):
        self.add_to_playlist(1)
        self.window.search_bar.setText('dnb')
        self.map.only_button.setChecked(True)
        self.wait_for_map()
        self.assertNotIn(self.key(1), self.map.data.row)
        self.select_in_playlist(1)
        self.assertIn(self.key(1), self.map.data.row)  # placed, no new layout
        self.assertIn(self.key(1), self.visible())
        self.assertEqual(len(self.map.data.vectors), len(self.map.data.keys))
        # Placed with the map's own centring: as similar to the mapped tracks as a fresh map of all of them says.
        self.map.select(self.key(1))
        self.assertTrue(self.map.suggestions.topLevelItemCount())
        self.window.search_bar.setText('dnb 1')        # the List changes: the new map gets the track again
        self.wait_for_map()
        self.assertIn(self.key(1), self.map.data.row)
        self.assertIn(self.key(1), self.visible())

    def test_an_unanalysed_playlist_track_is_reported(self):
        self.add_to_playlist(24)                      # track 24 has no embedding
        self.select_in_playlist(24)
        self.assertIn('0 of 1 selected Playlist tracks shown', self.map._base_status)


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
        self.assertIn('breaks 2', self.map.label_text.toPlainText())
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
        self.map.store.save_error(self.key(24), (1, 2), 'LibsndfileError: Unspecified internal error.')
        self.drop_on_map(self.root / 'track24.mp3')  # tried and failed: the message says so, not "not analysed"
        self.assertIn('track24.mp3 cannot be on the map', self.map.status.text())
        self.assertIn('LibsndfileError', self.map.status.text())


class ListGroupTests(MapWindowTestBase):
    """The map's groups in the List: the Group column and the Group colours switch."""

    def wait_for(self, condition, window=None):
        deadline = time.monotonic() + 60
        while not condition() and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.02)
        self.application.processEvents()

    def list_items(self, window=None):
        tree = (window or self.window).candidate_tree
        return {canonical_path(tree.topLevelItem(i).text(self.header['Path'])): tree.topLevelItem(i)
                for i in range(tree.topLevelItemCount())}

    @property
    def header(self):
        from songselector.config import HEADER_INDEX
        return HEADER_INDEX

    def test_switch_colours_rows_by_map_group_and_group_column_sorts_them(self):
        from songselector.config import COLOR_MAPPING_CATEGORY, GROUP_COLUMN
        from songselector.ui.similarity_map import group_colour
        self.assertIsNone(self.map.grouping.currentData())  # grouping off
        column = self.header[GROUP_COLUMN]
        self.assertFalse(self.window.candidate_tree.isColumnHidden(column))
        self.assertEqual({item.text(column) for item in self.list_items().values()}, {''})
        self.window.group_colours_switch.setChecked(True)
        self.assertEqual(self.map.grouping.currentData(), 'communities')  # chosen for the switch
        self.wait_for(lambda: bool(self.map.groups))
        items = self.list_items()
        for index in range(24):
            group = self.map.groups[self.key(index)]
            item = items[self.key(index)]
            self.assertEqual(item.text(column), str(group + 1))
            self.assertEqual(item.background(self.header['Artist']).color().rgb(), group_colour(group).rgb())
        self.assertEqual(items[self.key(24)].text(column), '')  # not analysed: no group, no tint
        self.assertEqual(items[self.key(24)].background(0).style(), 0)
        # Sorting by Group keeps each group together; tracks without one come last
        self.window.sort_by_column(column, True)
        tree = self.window.candidate_tree
        texts = [tree.topLevelItem(i).text(column) for i in range(tree.topLevelItemCount())]
        self.assertEqual(texts, sorted(texts[:-1], key=int) + [''])
        # Off: Traktor colours again, the Group column stays
        self.window.group_colours_switch.setChecked(False)
        traktor = self.list_items()[self.key(1)]  # Color 1
        self.assertEqual(traktor.background(0).color().rgb(), COLOR_MAPPING_CATEGORY[1].rgb())
        self.assertNotEqual(traktor.text(column), '')

    def test_switch_on_at_start_groups_without_opening_the_map(self):
        from songselector.config import GROUP_COLUMN
        from songselector.ui.main_window import MainWindow
        self.window.library_tabs.setCurrentIndex(0)
        self.window.group_colours_switch.setChecked(True)
        self.window.close()  # saves the settings
        self.application.processEvents()
        self.window = MainWindow()
        self.map = self.window.similarity_map
        self.assertIsNot(self.window.library_tabs.currentWidget(), self.map)
        self.assertTrue(self.window.group_colours_switch.isChecked())
        self.wait_for(lambda: bool(self.map.groups))
        column = self.header[GROUP_COLUMN]
        self.assertTrue(all(self.list_items()[self.key(i)].text(column) for i in range(24)))
        self.assertTrue(self.window.status_label.text().startswith('Grouped: '))

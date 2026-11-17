"""List columns asked for on 2026-11-17: the speed change to the master tempo, sorting by group then match; the
map's track names without a leading ' - '."""
import unittest

import pandas as pd
from test_song_selector_fields import GuiTestBase, track

from songselector.config import GROUP_COLUMN, HEADER_INDEX, MATCH_COLUMN, SPEED_COLUMN
from songselector.ui.main_window import speed_change_text
from songselector.ui.similarity_map import track_name

SPEED, GROUP, MATCH, TITLE = (HEADER_INDEX[name] for name in (SPEED_COLUMN, GROUP_COLUMN, MATCH_COLUMN, 'Title'))


class SpeedChangeTextTests(unittest.TestCase):
    def test_percent_with_one_decimal_and_a_sign(self):
        self.assertEqual(speed_change_text(120, 128), '+6.7%')
        self.assertEqual(speed_change_text(140, 128), '-8.6%')
        self.assertEqual(speed_change_text(128, 128), '+0.0%')
        self.assertEqual(speed_change_text(147.13, 128), '-13.0%')
        self.assertEqual(speed_change_text(None, 128), '')
        self.assertEqual(speed_change_text(0, 128), '')


class TrackNameTests(unittest.TestCase):
    def test_no_dash_for_a_missing_artist_or_title(self):
        self.assertEqual(track_name({'Artist': 'Desimal', 'Title': 'Hyperboria'}), 'Desimal - Hyperboria')
        self.assertEqual(track_name({'Artist': '', 'Title': 'Desimal - Hyperboria'}), 'Desimal - Hyperboria')
        self.assertEqual(track_name({'Artist': 'Desimal', 'Title': ' '}), 'Desimal')
        self.assertEqual(track_name({'Path': r'E:\music\untitled.mp3'}), 'untitled.mp3')


class ListColumnGuiTests(GuiTestBase):
    def setUp(self):
        super().setUp()
        self.library = pd.DataFrame([track(self.root / f'{name}.mp3', name, BPM=bpm)
                                     for name, bpm in (('slow', 100), ('even', 128), ('fast', 140), ('near', 125))])

    def column(self, window, column):
        tree = window.candidate_tree
        return {tree.topLevelItem(i).text(TITLE): tree.topLevelItem(i).text(column)
                for i in range(tree.topLevelItemCount())}

    def order(self, window):
        tree = window.candidate_tree
        return [tree.topLevelItem(i).text(TITLE) for i in range(tree.topLevelItemCount())]

    def test_speed_change_follows_the_master_tempo_and_sorts_as_a_number(self):
        window = self.window()
        window.bpm_slider.setValue(128)
        window.update_tree_after_slider()
        self.assertEqual(self.column(window, SPEED), {'slow': '+28.0%', 'even': '+0.0%', 'fast': '-8.6%', 'near': '+2.4%'})
        tree = window.candidate_tree
        self.assertFalse(tree.isColumnHidden(SPEED))
        self.assertEqual(tree.header().visualIndex(SPEED), tree.header().visualIndex(HEADER_INDEX['Original BPM']) + 1)
        self.assertFalse(window.playlist_tree.isColumnHidden(SPEED))
        window.sort_by_column(SPEED, True)
        self.assertEqual(self.order(window), ['fast', 'even', 'near', 'slow'])  # -8.6 < 0 < 2.4 < 28 (not as text)
        window.bpm_slider.setValue(140)
        window.update_tree_after_slider()
        self.assertEqual(self.column(window, SPEED)['fast'], '+0.0%')

    def test_complex_search_on_the_speed_change_follows_the_master_tempo(self):
        window = self.window()
        window.bpm_slider.setValue(128)
        window.update_tree_after_slider()
        window.current_advanced_search = {'enabled': True, 'filters': [
            {'column': SPEED_COLUMN, 'condition': 'within ± (%)', 'value': '8'}]}
        window.advanced_filters = window.current_advanced_search['filters']
        window.filter_items()
        shown = lambda: sorted(title for title, _speed in self.column(window, SPEED).items()  # noqa: E731
                               if not self.item_hidden(window, title))
        self.assertEqual(shown(), ['even', 'near'])          # 0 % and +2.4 %; fast -8.6 %, slow +28 %
        window.bpm_slider.setValue(140)
        window.update_tree_after_slider()
        self.assertEqual(shown(), ['fast'])                  # now near is +12 %, even +9.4 %

    def test_the_dialog_offers_the_speed_conditions(self):
        from songselector.config import COMPLEX_SEARCH_COLUMNS
        from songselector.ui.advanced_search_dialog import AdvancedSearchRow
        self.assertIn(SPEED_COLUMN, COMPLEX_SEARCH_COLUMNS)
        row = AdvancedSearchRow(COMPLEX_SEARCH_COLUMNS)
        row.column_combo.setCurrentText(SPEED_COLUMN)
        conditions = [row.condition_combo.itemText(i) for i in range(row.condition_combo.count())]
        self.assertIn('within ± (%)', conditions)
        self.assertIn('at most (<=)', conditions)
        row.condition_combo.setCurrentText('within ± (%)')
        self.assertIn('percent', row.value_edit.placeholderText())
        row.column_combo.setCurrentText('Genre')
        self.assertNotIn('within ± (%)', [row.condition_combo.itemText(i) for i in range(row.condition_combo.count())])

    def item_hidden(self, window, title):
        tree = window.candidate_tree
        return next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                    if tree.topLevelItem(i).text(TITLE) == title).isHidden()

    def test_sorting_by_group_puts_the_best_match_first_within_each_group(self):
        window = self.window()
        tree = window.candidate_tree
        values = {'slow': ('1', '20%'), 'even': ('2', '45%'), 'fast': ('1', '33%'), 'near': ('1', '')}
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            item.setText(GROUP, values[item.text(TITLE)][0])
            item.setText(MATCH, values[item.text(TITLE)][1])
        window.sort_by_column(GROUP, True)
        self.assertEqual(self.order(window), ['fast', 'slow', 'near', 'even'])  # group 1: 33%, 20%, none; group 2
        window.sort_by_column(GROUP, False)
        self.assertEqual(self.order(window), ['even', 'fast', 'slow', 'near'])  # groups reversed, matches still best first


class SpeedSearchTests(unittest.TestCase):
    def test_within_and_outside_a_speed_change(self):
        from songselector.core.search_filters import matches_condition, parse_number
        self.assertEqual(parse_number('+6.2%'), 6.2)
        self.assertEqual(parse_number('-13,0 %'), -13.0)
        within, outside = 'within ± (%)', 'outside ± (%)'
        self.assertTrue(matches_condition('+6.2%', within, '8', SPEED_COLUMN))
        self.assertTrue(matches_condition('-8.0%', within, '8', SPEED_COLUMN))
        self.assertFalse(matches_condition('-9.0%', within, '8', SPEED_COLUMN))
        self.assertTrue(matches_condition('-9.0%', outside, '8', SPEED_COLUMN))
        self.assertTrue(matches_condition('+3.0%', within, '-8', SPEED_COLUMN))  # the sign of the limit does not matter
        self.assertFalse(matches_condition('', within, '8', SPEED_COLUMN))       # unknown BPM
        self.assertFalse(matches_condition('120', within, '8', 'Original BPM'))  # only for the speed change
        self.assertTrue(matches_condition('-5.0%', 'at least (>=)', '-6', SPEED_COLUMN))  # signed comparisons too


class AlwaysOnTopTests(GuiTestBase):
    def test_always_on_top_for_both_windows_and_remembered(self):
        from PyQt5.QtCore import Qt
        window = self.window()
        window.show()
        self.assertFalse(window.windowFlags() & Qt.WindowStaysOnTopHint)
        window.set_map_detached(True)
        window.on_top_action.trigger()
        self.application.processEvents()
        self.assertTrue(window.windowFlags() & Qt.WindowStaysOnTopHint)
        self.assertTrue(window.map_window.windowFlags() & Qt.WindowStaysOnTopHint)
        self.assertTrue(window.isVisible())             # changing the flag hides a window: shown again
        self.assertTrue(window.map_window.isVisible())
        window.set_map_detached(False)
        window.set_map_detached(True)                   # a new map window gets it too
        self.assertTrue(window.map_window.windowFlags() & Qt.WindowStaysOnTopHint)
        window.set_map_detached(False)
        restarted = self.restart(window)                # remembered
        self.assertTrue(restarted.windowFlags() & Qt.WindowStaysOnTopHint)
        self.assertTrue(restarted.on_top_action.isChecked())
        restarted.on_top_action.trigger()
        self.assertFalse(restarted.windowFlags() & Qt.WindowStaysOnTopHint)


if __name__ == '__main__':
    unittest.main()

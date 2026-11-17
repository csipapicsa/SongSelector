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

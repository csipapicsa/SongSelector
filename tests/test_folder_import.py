"""Dropping or choosing folders imports their audio files, including all subfolders."""
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile
from PyQt5.QtCore import QCoreApplication, QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt5.QtGui import QDragEnterEvent, QDropEvent
from test_imports import tagged_file
from test_song_selector_fields import GuiTestBase

from traktor_key_calculator.config import HEADER_INDEX
from traktor_key_calculator.ui.tree_widgets import dropped_paths, find_audio_files


def mime_for(*paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    return mime


class FolderImportTests(GuiTestBase):
    def setUp(self):
        super().setUp()
        self.music = self.root / 'music'
        (self.music / 'sub' / 'deeper').mkdir(parents=True)
        (self.music / 'empty').mkdir()
        tagged_file(self.music / 'a.mp3')
        tagged_file(self.music / 'sub' / 'B.MP3')
        soundfile.write(str(self.music / 'sub' / 'deeper' / 'c.wav'), np.zeros((441, 2)), 44100)
        (self.music / 'sub' / 'notes.txt').write_text('not audio')
        (self.root / 'other').mkdir()
        soundfile.write(str(self.root / 'other' / 'd.flac'), np.zeros((441, 2)), 44100)
        self.expected = [self.music / 'a.mp3', self.music / 'sub' / 'B.MP3', self.music / 'sub' / 'deeper' / 'c.wav']

    def drop(self, tree, *paths):
        mime = mime_for(*paths)
        enter = QDragEnterEvent(QPoint(8, 8), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QCoreApplication.sendEvent(tree.viewport(), enter)
        self.assertTrue(enter.isAccepted())
        QCoreApplication.sendEvent(tree.viewport(), QDropEvent(QPointF(8, 8), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
        self.application.processEvents()

    @staticmethod
    def paths(tree):
        return {Path(tree.topLevelItem(i).text(HEADER_INDEX['Path'])) for i in range(tree.topLevelItemCount())}

    def test_folders_are_searched_recursively_in_a_stable_order(self):
        self.assertEqual([Path(p) for p in find_audio_files([self.music])], self.expected)
        self.assertEqual([Path(p) for p in find_audio_files([self.music, self.root / 'other' / 'd.flac'])],
                         self.expected + [self.root / 'other' / 'd.flac'])
        self.assertEqual(find_audio_files([self.music / 'empty', self.music / 'sub' / 'notes.txt']), [])

    def test_dragging_checks_only_the_dropped_items(self):
        self.assertEqual(dropped_paths(mime_for(self.music, self.music / 'sub' / 'notes.txt')), [str(self.music)])

    def test_dropping_a_folder_on_the_library_imports_all_audio_files_below_it(self):
        window = self.window()
        self.drop(window.candidate_tree, self.music)
        self.assertTrue(set(self.expected) <= self.paths(window.candidate_tree))
        self.assertNotIn(self.music / 'sub' / 'notes.txt', self.paths(window.candidate_tree))
        self.assertIn('Imported 3 track(s)', window.status_label.text())

    def test_dropping_folders_and_files_on_the_playlist(self):
        window = self.window()
        self.drop(window.playlist_tree, self.music / 'sub', self.root / 'other' / 'd.flac')
        self.assertEqual(self.paths(window.playlist_tree), set(self.expected[1:]) | {self.root / 'other' / 'd.flac'})

    def test_empty_folder_reports_that_nothing_was_found(self):
        window = self.window()
        before = window.candidate_tree.topLevelItemCount()
        self.drop(window.candidate_tree, self.music / 'empty')
        self.assertEqual(window.candidate_tree.topLevelItemCount(), before)
        self.assertEqual(window.status_label.text(), 'No MP3, WAV or FLAC files in what was dropped')

    def test_add_folder_menu_with_progress_dialog_and_cancel(self):
        window = self.window()
        with patch('traktor_key_calculator.ui.main_window.QFileDialog.getExistingDirectory', return_value=str(self.music)), \
                patch('traktor_key_calculator.ui.main_window.PROGRESS_THRESHOLD', 1):
            window.choose_audio_folder()
        self.assertTrue(set(self.expected) <= self.paths(window.candidate_tree))
        cancel_after_first = iter([False, True, True])
        with patch('traktor_key_calculator.ui.main_window.PROGRESS_THRESHOLD', 1), \
                patch('traktor_key_calculator.ui.main_window.QProgressDialog.wasCanceled',
                      side_effect=lambda: next(cancel_after_first)):
            imported = window.import_audio_files([str(self.root / 'other' / 'd.flac')] + [str(p) for p in self.expected])
        self.assertEqual(len(imported), 1)
        self.assertIn('cancelled', window.status_label.text())

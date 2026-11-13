"""Renaming the app to SongSelector must not lose anyone's settings or environment setup."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from songselector.config import migrate_legacy_settings
from songselector.env import getenv


class LegacySettingsMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.folder = Path(self.temp.name)
        self.new = self.folder / 'SongSelector_settings.json'
        self.old = self.folder / 'SpotNextTrack_settings.json'

    def tearDown(self):
        self.temp.cleanup()

    def migrate(self):
        return migrate_legacy_settings(self.new, self.old)

    def test_old_settings_are_moved_to_the_new_name_and_kept_as_backup(self):
        self.old.write_text(json.dumps({'Master Tempo': 174}))
        self.assertTrue(self.migrate())
        self.assertEqual(json.loads(self.new.read_text())['Master Tempo'], 174)
        self.assertFalse(self.old.exists())
        self.assertEqual(json.loads((self.folder / 'SpotNextTrack_settings.json.bak').read_text())['Master Tempo'], 174)

    def test_runs_only_once_so_a_settings_reset_stays_reset(self):
        self.old.write_text(json.dumps({'Master Tempo': 174}))
        self.migrate()
        self.new.unlink()  # what "reset settings" does
        self.assertFalse(self.migrate())
        self.assertFalse(self.new.exists())

    def test_existing_new_settings_win_over_old_ones(self):
        self.new.write_text(json.dumps({'Master Tempo': 128}))
        self.old.write_text(json.dumps({'Master Tempo': 174}))
        self.assertFalse(self.migrate())
        self.assertEqual(json.loads(self.new.read_text())['Master Tempo'], 128)
        self.assertTrue(self.old.exists())

    def test_fresh_install_has_nothing_to_migrate(self):
        self.assertFalse(self.migrate())
        self.assertEqual(list(self.folder.iterdir()), [])


class EnvironmentVariableTests(unittest.TestCase):
    def test_new_name_first_then_the_old_name_then_the_default(self):
        with patch.dict(os.environ, {'SONGSELECTOR_X_TEST': 'new', 'TRAKTOR_X_TEST': 'old'}):
            self.assertEqual(getenv('X_TEST'), 'new')
        with patch.dict(os.environ, {'TRAKTOR_X_TEST': 'old'}):
            self.assertEqual(getenv('X_TEST'), 'old')
        self.assertEqual(getenv('X_TEST', 'default'), 'default')

    def test_an_empty_new_value_is_a_value(self):
        # SONGSELECTOR_EMBEDDING_MODEL='' switches the default model off; it must not fall back to the old name.
        with patch.dict(os.environ, {'SONGSELECTOR_X_TEST': '', 'TRAKTOR_X_TEST': 'old'}):
            self.assertEqual(getenv('X_TEST'), '')


if __name__ == '__main__':
    unittest.main(verbosity=2)

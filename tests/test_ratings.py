import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
from traktor_key_calculator.core.track_import import enrich_ratings, TrackImporter
from traktor_key_calculator.core.traktor_collection import TraktorCollection, canonical_path
from test_imports import tagged_file, make_collection


class RatingEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['TRAKTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)
        self.track = tagged_file(self.root/'rated.mp3')
        self.nml = self.root/'collection.nml'
        make_collection(self.nml, [(self.track, 0, 100)])
        self.collection = TraktorCollection(self.nml)

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_ratings_filled_without_changing_input_or_existing_values(self):
        table = pd.DataFrame({'File_Path':[str(self.track)]*4,
                              'Rating':[None,4,0,'']})
        result = enrich_ratings(table,self.collection)
        self.assertEqual(result['Rating'].tolist(),[5,4,0,5])
        self.assertEqual(table['Rating'].tolist(),[None,4,0,''])

    def test_exact_paths_only_and_unrated_tracks_remain_blank(self):
        self.nml.write_text(self.nml.read_text().replace('RANKING="255"','RANKING="0"'))
        table = pd.DataFrame({'File_Path':[str(self.track), str(self.root/'other'/'rated.mp3')]})
        result = enrich_ratings(table,self.collection)
        self.assertTrue(result['Rating'].isna().all())
        self.nml.write_text(self.nml.read_text().replace('RANKING="0"','RANKING="255"'))
        result = enrich_ratings(table,self.collection)
        self.assertEqual(result.iloc[0]['Rating'],5)
        self.assertTrue(pd.isna(result.iloc[1]['Rating']))

    def test_unavailable_collection_and_empty_library_are_safe(self):
        collection=TraktorCollection(self.root/'missing.nml')
        result=enrich_ratings(pd.DataFrame({'File_Path':[str(self.track)]}),collection)
        self.assertTrue(result['Rating'].isna().all())
        self.assertTrue(enrich_ratings(pd.DataFrame(),collection).empty)


class RatingGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application=QApplication.instance() or QApplication([])

    def setUp(self):
        from traktor_key_calculator.config import SETTINGS_DEFAULT
        self.temp=tempfile.TemporaryDirectory(dir=os.environ['TRAKTOR_APP_DATA_DIR'])
        self.root=Path(self.temp.name)
        self.track=tagged_file(self.root/'rated.mp3')
        self.nml=self.root/'collection.nml'
        make_collection(self.nml,[(self.track,0,100)])
        self.settings_path=self.root/'settings.json'
        settings=copy.deepcopy(SETTINGS_DEFAULT)
        settings.update({'Traktor collection':str(self.nml),'Search columns':['Artist','Title'],
                         'Advanced search':{'enabled':False,'filters':[]}})
        for side in ('left','right'):
            settings['Visible column '+side]=['Artist','Title','Original BPM']
            settings['Column sizes '+side]={'Rating':0}
        self.settings_path.write_text(json.dumps(settings))
        self.patches=[patch('traktor_key_calculator.ui.main_window.SETTINGS_FILE',str(self.settings_path))]
        for p in self.patches: p.start()
        self.windows=[]

    def tearDown(self):
        for window in self.windows: window.close()
        for p in self.patches: p.stop()
        self.temp.cleanup()

    def window(self):
        from traktor_key_calculator.ui.main_window import TraktorKeyCalculator
        window=TraktorKeyCalculator()
        self.windows.append(window)
        return window

    def library(self):
        return pd.DataFrame([{'Artist':'Test','Title':'Rated','BPM':100,
                             'File_Path':str(self.track),'Musical_Key_Base':'C','BaseMinorOrMajor':'major'},
                            {'Artist':'Test','Title':'Unrated','BPM':100,
                             'File_Path':str(self.root/'unrated.mp3'),'Musical_Key_Base':'C','BaseMinorOrMajor':'major'}])

    def test_legacy_settings_upgrade_once_and_user_choices_survive_restart(self):
        from traktor_key_calculator.config import HEADER_INDEX
        window=self.window()
        for tree in (window.candidate_tree,window.playlist_tree):
            self.assertFalse(tree.isColumnHidden(HEADER_INDEX['Rating']))
            self.assertGreater(tree.columnWidth(HEADER_INDEX['Rating']),0)
        self.assertTrue(window.search_column_actions['Rating'].isChecked())
        window.search_column_actions['Rating'].setChecked(False)
        window.playlist_tree.setColumnHidden(HEADER_INDEX['Rating'],True)
        window.close()
        restored=self.window()
        self.assertFalse(restored.search_column_actions['Rating'].isChecked())
        self.assertTrue(restored.playlist_tree.isColumnHidden(HEADER_INDEX['Rating']))

    def test_existing_library_ratings_visible_in_both_panels_and_searchable(self):
        from traktor_key_calculator.config import HEADER_INDEX
        window=self.window()
        window.table=window._load_library(self.library())
        window.populate_tree()
        item=next(window.candidate_tree.topLevelItem(i) for i in range(2)
                  if window.candidate_tree.topLevelItem(i).text(HEADER_INDEX['Title'])=='Rated')
        self.assertEqual(item.text(HEADER_INDEX['Rating']),'5')  # the number, for sorting and search
        for tree in (window.candidate_tree, window.playlist_tree):  # shown as stars
            for column in ('Rating', 'Rating - Song Selector'):
                self.assertEqual(tree.itemDelegateForColumn(HEADER_INDEX[column]).displayText('5', None), '★★★★★')
        for name,action in window.search_column_actions.items(): action.setChecked(name=='Rating')
        window.search_bar.setText('5')
        window.filter_items()
        self.assertFalse(item.isHidden())
        self.assertEqual(sum(not window.candidate_tree.topLevelItem(i).isHidden() for i in range(2)),1)
        window.search_bar.clear()
        window.current_advanced_search={'enabled':True,'filters':[]}
        window.advanced_filters=[{'column':'Rating','condition':'at least (>=)','value':'4'}]
        window.filter_items()
        self.assertFalse(item.isHidden())
        self.assertEqual(sum(not window.candidate_tree.topLevelItem(i).isHidden() for i in range(2)),1)

        window._add_to_playlist(window.table.iloc[0])
        self.assertEqual(window.playlist_tree.topLevelItem(0).text(HEADER_INDEX['Rating']),'5')

    def test_refresh_csv_load_and_collection_link_enrich_ratings(self):
        window=self.window()
        table=self.library()
        window.library_store.upsert_tracks(table.to_dict('records'))  # Refresh rebuilds from the collection
        window.refresh_data()
        self.assertEqual(window.table.iloc[0]['Rating'],5)
        csv=self.root/'library.csv'
        table.to_csv(csv,index=False)
        with patch('traktor_key_calculator.ui.main_window.QFileDialog.getOpenFileName',return_value=(str(csv),'')):
            window.load_csv()
        self.assertEqual(window.table.iloc[0]['Rating'],5)
        window.table=table
        with patch('traktor_key_calculator.ui.main_window.QFileDialog.getOpenFileName',return_value=(str(self.nml),'')):
            window.choose_traktor_collection()
        self.assertEqual(window.table.iloc[0]['Rating'],5)

    def test_imported_tag_rating_takes_precedence_over_collection_rating(self):
        from traktor_key_calculator.config import HEADER_INDEX
        window=self.window()
        window.table=window._load_library(self.library())
        window.import_audio_files([str(self.track)],to_playlist=True)
        row=window.table.loc[window.table['File_Path']==str(self.track)].iloc[0]
        self.assertEqual(row['Rating'],4)
        self.assertEqual(window.playlist_tree.topLevelItem(0).text(HEADER_INDEX['Rating']),'4')
        reloaded=window._load_library(self.library())
        self.assertEqual(reloaded.iloc[0]['Rating'],4)


if __name__=='__main__':
    unittest.main(verbosity=2)

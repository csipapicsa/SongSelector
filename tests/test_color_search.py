import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
from traktor_key_calculator.core.color_search import COLOR_NAMES, parse_color_search, replace_color_filter
from traktor_key_calculator.core.search_filters import matches_condition


class ColorSearchTests(unittest.TestCase):
    def test_named_colors_aliases_lists_and_case(self):
        query=parse_color_search('tribal COLOR:Red, Orange|BLUE')
        self.assertEqual(query.text,'tribal')
        self.assertTrue(query.matches('1'))
        self.assertTrue(query.matches('2.0'))
        self.assertTrue(query.matches(5))
        self.assertFalse(query.matches(4))
        self.assertTrue(parse_color_search('colour:purple').matches(7))
        self.assertTrue(parse_color_search('color:magenta').matches(7))
        for number,name in COLOR_NAMES.items():
            self.assertTrue(parse_color_search('color:'+name).matches(number))

    def test_text_combination_exclusions_and_repeated_colors(self):
        query=parse_color_search('alpha color:red beta -color:orange')
        self.assertEqual(query.text,'alpha beta')
        self.assertTrue(query.matches(1))
        self.assertFalse(query.matches(2))
        query=parse_color_search('color:red color:blue -color:blue')
        self.assertTrue(query.matches(1))
        self.assertFalse(query.matches(5))
        self.assertTrue(parse_color_search('tribal -color:blue').matches(4))
        self.assertFalse(parse_color_search('tribal -color:blue').matches(5))

    def test_none_invalid_and_plain_text(self):
        for value in (0,'0','',None,'nan'):
            self.assertTrue(parse_color_search('color:none').matches(value))
        for query in ('color:bluu','color:','color:99','color:blue,'):
            parsed=parse_color_search(query)
            self.assertTrue(parsed.error)
            self.assertFalse(parsed.matches(5))
        self.assertFalse(parse_color_search('color:blue').matches('5.9'))
        query=parse_color_search('Blue Monday discolor:red')
        self.assertEqual(query.text,'Blue Monday discolor:red')
        self.assertTrue(query.matches(4))

    def test_menu_replacement_preserves_text_and_exclusions(self):
        text=replace_color_filter('tribal color:red -colour:blue',{2,4})
        query=parse_color_search(text)
        self.assertEqual(query.text,'tribal')
        self.assertEqual(query.included,{2,4})
        self.assertEqual(query.excluded,{5})
        cleared=parse_color_search(replace_color_filter(text,set()))
        self.assertFalse(cleared.has_included)
        self.assertEqual(cleared.excluded,{5})
        self.assertEqual(cleared.text,'tribal')

    def test_complex_search_color_names_and_existing_numeric_conditions(self):
        self.assertTrue(matches_condition('5','is','blue','Color'))
        self.assertTrue(matches_condition('2','contains','red,orange','Color'))
        self.assertTrue(matches_condition('7','is','purple','Color'))
        self.assertTrue(matches_condition('0','is','none','Color'))
        self.assertFalse(matches_condition('5','is not','blue','Color'))
        self.assertTrue(matches_condition('4','does not contain','blue','Color'))
        self.assertFalse(matches_condition('5','is not','bluu','Color'))
        self.assertTrue(matches_condition('5','greater than','3','Color'))
        self.assertTrue(matches_condition('2','contains','2','Color'))
        self.assertTrue(matches_condition('Blue Monday','contains','blue','Title'))


class ColorSearchGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application=QApplication.instance() or QApplication([])

    def setUp(self):
        from traktor_key_calculator.config import SETTINGS_DEFAULT
        self.temp=tempfile.TemporaryDirectory(dir=os.environ['TRAKTOR_APP_DATA_DIR'])
        self.root=Path(self.temp.name)
        self.settings_path=self.root/'settings.json'
        settings=copy.deepcopy(SETTINGS_DEFAULT)
        settings.update({'Traktor collection':'','Advanced search':{'enabled':False,'filters':[]},'Search columns':['Title']})
        self.settings_path.write_text(json.dumps(settings))
        self.settings_patch=patch('traktor_key_calculator.ui.main_window.SETTINGS_FILE',str(self.settings_path))
        self.settings_patch.start()
        from traktor_key_calculator.ui.main_window import TraktorKeyCalculator
        self.window=TraktorKeyCalculator()
        rows=[]
        for title,color,rating in [('tribal red',1,4),('tribal orange',2,2),('tribal blue',5,5),('Blue Monday',4,4),('tribal uncolored',0,None)]:
            rows.append({'Title':title,'Artist':'Test','Color':color,'Rating':rating,'BPM':125,
                         'Musical_Key_Base':'C','BaseMinorOrMajor':'major','File_Path':str(self.root/(title+'.mp3'))})
        self.window.table=pd.DataFrame(rows)
        self.window.populate_tree()
        # Explicit color filters must work even when Color is disabled under Search Columns.
        for name,action in self.window.search_column_actions.items(): action.setChecked(name=='Title')

    def tearDown(self):
        self.window.close()
        self.settings_patch.stop()
        self.temp.cleanup()

    def visible(self):
        from traktor_key_calculator.config import HEADER_INDEX
        tree=self.window.candidate_tree
        return {tree.topLevelItem(i).text(HEADER_INDEX['Title']) for i in range(tree.topLevelItemCount())
                if not tree.topLevelItem(i).isHidden()}

    def test_search_bar_names_multiple_colors_exclusions_and_plain_title(self):
        for text,expected in [('color:blue',{'tribal blue'}),('tribal color:red,orange',{'tribal red','tribal orange'}),
                              ('tribal -color:blue',{'tribal red','tribal orange','tribal uncolored'}),
                              ('color:none',{'tribal uncolored'}),('Blue Monday',{'Blue Monday'})]:
            self.window.search_bar.setText(text)
            self.assertEqual(self.visible(),expected)
        self.window.coloring_mode='key'
        self.window.populate_tree()
        self.window.search_bar.setText('color:blue')
        self.assertEqual(self.visible(),{'tribal blue'})

    def test_actual_menu_actions_add_remove_colors_and_sync_with_typed_query(self):
        self.window.search_bar.setText('tribal')
        self.window.color_search_actions[1].trigger()
        self.assertEqual(self.visible(),{'tribal red'})
        self.window.color_search_actions[2].trigger()
        self.assertEqual(self.visible(),{'tribal red','tribal orange'})
        self.assertEqual(self.window.color_search_button.text(),'Colors (2)')
        self.assertFalse(self.window.color_search_actions[2].icon().isNull())
        self.window.search_bar.setText('color:blue')
        self.assertTrue(self.window.color_search_actions[5].isChecked())
        self.assertFalse(self.window.color_search_actions[1].isChecked())
        self.window.search_bar.setText('tribal color:red -color:blue')
        self.window.color_search_menu.actions()[0].trigger()
        self.assertEqual(self.visible(),{'tribal red','tribal orange','tribal uncolored'})
        self.assertEqual(parse_color_search(self.window.search_bar.text()).excluded,{5})

    def test_color_search_combines_with_rating_filter_and_hides_playlist_members(self):
        self.window.current_advanced_search={'enabled':True,'filters':[]}
        self.window.advanced_filters=[{'column':'Rating','condition':'at least (>=)','value':'4'}]
        self.window.search_bar.setText('tribal color:red,orange,blue')
        self.assertEqual(self.visible(),{'tribal red','tribal blue'})
        self.window.hide_playlist_action.setChecked(True)  # View > Hide playlist tracks in the library
        self.window._add_to_playlist(self.window.table.iloc[0])
        self.window.filter_items()
        self.assertEqual(self.visible(),{'tribal blue'})
        self.window.advanced_filters=[{'column':'Color','condition':'is','value':'blue'}]
        self.window.search_bar.clear()
        self.assertEqual(self.visible(),{'tribal blue'})

    def test_invalid_color_shows_help_and_recovers_on_correction(self):
        self.window.search_bar.setText('color:bluu')
        self.assertEqual(self.visible(),set())
        self.assertIn('Unknown color',self.window.status_label.text())
        self.window.search_bar.setText('color:blue')
        self.assertEqual(self.visible(),{'tribal blue'})
        self.assertIn('Displaying',self.window.status_label.text())

    def test_complex_dialog_accepts_color_names_validates_and_restores_them(self):
        from PyQt5.QtCore import QTimer
        def configure():
            dialog=self.window.advanced_search_dialog
            dialog.checkbox_enable.setChecked(True)
            row=dialog.filter_rows[0]
            row.column_combo.setCurrentText('Color')
            row.condition_combo.setCurrentText('is')
            self.assertIsNotNone(row.value_edit.completer())
            row.value_edit.setText('bluu')
            with patch('traktor_key_calculator.ui.advanced_search_dialog.QMessageBox.warning') as warning:
                dialog.button_ok.click()
                warning.assert_called_once()
            row.value_edit.setText('blue')
            dialog.button_ok.click()
        QTimer.singleShot(0,configure)
        self.window.open_advanced_search()
        self.assertEqual(self.visible(),{'tribal blue'})
        observed=[]
        def inspect():
            dialog=self.window.advanced_search_dialog
            observed.append(dialog.filter_rows[0].value_edit.text())
            dialog.button_cancel.click()
        QTimer.singleShot(0,inspect)
        self.window.open_advanced_search()
        self.assertEqual(observed,['blue'])


if __name__=='__main__':
    unittest.main(verbosity=2)

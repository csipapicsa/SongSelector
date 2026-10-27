import os
import unittest
from unittest.mock import patch
from traktor_key_calculator.core.search_filters import matches_condition, parse_number, NUMERIC_COMPARISONS


class ComparisonTests(unittest.TestCase):
    def test_numeric_boundaries_decimals_and_missing_values(self):
        self.assertTrue(matches_condition('9', 'less than', '100', 'Original BPM'))
        self.assertFalse(matches_condition('100', 'less than', '9', 'Original BPM'))
        self.assertFalse(matches_condition('120', 'greater than', '120', 'Original BPM'))
        self.assertFalse(matches_condition('120', 'less than', '120', 'Original BPM'))
        self.assertTrue(matches_condition('120', 'at least (>=)', '120', 'Original BPM'))
        self.assertTrue(matches_condition('120', 'at most (<=)', '120', 'Original BPM'))
        self.assertTrue(matches_condition('128.5', 'greater than', '128,4', 'Original BPM'))
        self.assertTrue(matches_condition('4', 'greater than', '3', 'Rating'))
        self.assertFalse(matches_condition('130', 'greater than', '120', 'Genre'))
        for bad in ('Unknown', '', 'nan', 'inf', 'not a number', None):
            self.assertFalse(matches_condition(bad, 'greater than', '0', 'Original BPM'))
            self.assertIsNone(parse_number(bad))

    def test_existing_text_conditions(self):
        self.assertTrue(matches_condition('Tribal House', 'contains', 'tribal', 'Genre'))
        self.assertTrue(matches_condition('Tribal House', 'does not contain', 'techno', 'Genre'))
        self.assertTrue(matches_condition('Tribal', 'is', 'tribal', 'Genre'))
        self.assertTrue(matches_condition('House', 'is not', 'tribal', 'Genre'))


class NumericSearchGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application=QApplication.instance() or QApplication([])

    def test_numeric_options_follow_column_selection(self):
        from traktor_key_calculator.ui.advanced_search_dialog import AdvancedSearchRow
        row=AdvancedSearchRow(['Genre', 'Original BPM', 'Rating', 'Color', 'Artist'])
        def options():
            return [row.condition_combo.itemText(i) for i in range(row.condition_combo.count())]
        self.assertNotIn('greater than',options())
        row.column_combo.setCurrentText('Original BPM')
        for option in NUMERIC_COMPARISONS:
            self.assertIn(option,options())
        row.condition_combo.setCurrentText('greater than')
        row.column_combo.setCurrentText('Rating')
        self.assertEqual(row.condition_combo.currentText(),'greater than')
        row.column_combo.setCurrentText('Artist')
        self.assertEqual(row.condition_combo.currentText(),'contains')
        self.assertNotIn('less than',options())
        row.close()

    def test_dialog_accepts_decimals_and_rejects_invalid_numeric_input(self):
        from traktor_key_calculator.ui.advanced_search_dialog import AdvancedSearchDialog
        from PyQt5.QtWidgets import QDialog
        from PyQt5.QtTest import QTest
        from PyQt5.QtCore import Qt
        dialog=AdvancedSearchDialog(['Genre','Original BPM'])
        row=dialog.filter_rows[0]
        row.column_combo.setCurrentText('Original BPM')
        row.condition_combo.setCurrentText('greater than')
        row.value_edit.setText('not a number')
        dialog.show()
        with patch('traktor_key_calculator.ui.advanced_search_dialog.QMessageBox.warning') as warning:
            QTest.mouseClick(dialog.button_ok,Qt.LeftButton)
            self.assertEqual(dialog.result(),QDialog.Rejected)
            warning.assert_called_once()
            row.value_edit.setText('128,5')
            QTest.mouseClick(dialog.button_ok,Qt.LeftButton)
            self.assertEqual(dialog.result(),QDialog.Accepted)
        self.assertEqual(dialog.get_active_filters()[0]['value'],'128,5')
        dialog.close()

    def make_window(self):
        from traktor_key_calculator.config import init_settings
        from traktor_key_calculator.ui.main_window import TraktorKeyCalculator
        import pandas as pd
        init_settings()
        window=TraktorKeyCalculator()
        rows=[]
        for title,bpm,genre,rating,color in [('middle',125.5,'tribal',4,2),
                                             ('lower',120,'tribal',2,5),
                                             ('upper',130,'tribal',4,5),
                                             ('other genre',125,'house',1,2),
                                             ('unknown',None,'tribal',None,0)]:
            rows.append({'Artist':'Test','Title':title,'BPM':bpm,'Genre':genre,'Rating':rating,'Color':color,
                         'File_Path':rf'E:\test\{title}.mp3','Musical_Key_Base':'C','BaseMinorOrMajor':'major'})
        window.table=pd.DataFrame(rows)
        window.populate_tree()
        return window

    def visible_titles(self,window):
        from traktor_key_calculator.config import HEADER_INDEX
        return {window.candidate_tree.topLevelItem(i).text(HEADER_INDEX['Title'])
                for i in range(window.candidate_tree.topLevelItemCount())
                if not window.candidate_tree.topLevelItem(i).isHidden()}

    def test_actual_dialog_combines_genre_and_numeric_range_and_restores_settings(self):
        from PyQt5.QtCore import QTimer
        from traktor_key_calculator.ui.main_window import TraktorKeyCalculator
        window=self.make_window()
        rules=[('Genre','contains','tribal'),('Original BPM','greater than','120'),
               ('Original BPM','less than','130')]
        def configure():
            dialog=window.advanced_search_dialog
            dialog.checkbox_enable.setChecked(True)
            for row,(column,condition,value) in zip(dialog.filter_rows,rules):
                row.column_combo.setCurrentText(column)
                row.condition_combo.setCurrentText(condition)
                row.value_edit.setText(value)
            dialog.button_ok.click()
        QTimer.singleShot(0,configure)
        window.open_advanced_search()
        self.assertEqual(self.visible_titles(window),{'middle'})
        window.close()
        restored=TraktorKeyCalculator()
        self.assertEqual(restored.current_advanced_search['filters'][1]['condition'],'greater than')
        seen=[]
        def inspect_restored():
            dialog=restored.advanced_search_dialog
            seen.append(dialog.filter_rows[1].condition_combo.currentText())
            dialog.button_cancel.click()
        QTimer.singleShot(0,inspect_restored)
        restored.open_advanced_search()
        self.assertEqual(seen,['greater than'])
        restored.close()

    def test_integer_rating_and_color_filters(self):
        window=self.make_window()
        rules=[{'column':'Rating','condition':'at least (>=)','value':'4'},
               {'column':'Color','condition':'less than','value':'3'}]
        window.current_advanced_search={'enabled':True,'filters':rules}
        window.advanced_filters=rules
        window.filter_items()
        self.assertEqual(self.visible_titles(window),{'middle'})
        window.close()


if __name__=='__main__':
    unittest.main(verbosity=2)

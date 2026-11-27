import unittest
from unittest.mock import patch

from songselector.core.search_filters import NUMERIC_COMPARISONS, matches_condition, parse_number


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

    def test_match_filters_description_results_and_lets_tracks_without_a_match_through(self):
        # Asked 2026-11-27: the description Match ('31%', -100 % to 100 %) as an Advanced Search criterion.
        self.assertTrue(matches_condition('31%', 'at least (>=)', '30', 'Match'))
        self.assertFalse(matches_condition('29%', 'at least (>=)', '30', 'Match'))
        self.assertTrue(matches_condition('-12%', 'less than', '0', 'Match'))
        self.assertTrue(matches_condition('31%', 'greater than', '30.5%', 'Match'))
        # No description search shown: no Match value, and the rule does not hide every track.
        for empty in ('', ' ', None):
            self.assertTrue(matches_condition(empty, 'at least (>=)', '30', 'Match'))

    def test_active_filters_skip_unticked_rules_and_rows_saved_with_the_none_column(self):
        from songselector.core.search_filters import NO_COLUMN, active_filters
        rules = [{'column': 'Genre', 'condition': 'is', 'value': 'house', 'active': True},
                 {'column': 'Genre', 'condition': 'is', 'value': 'techno', 'active': False},
                 {'column': 'Genre', 'condition': 'is', 'value': 'saved before the tick'},
                 {'column': NO_COLUMN, 'condition': 'is', 'value': 'switched off the old way'},
                 {'column': 'Genre', 'condition': 'is', 'value': '', 'active': True}]
        self.assertEqual([f['value'] for f in active_filters(rules)], ['house', 'saved before the tick'])

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

    def test_match_offers_only_number_comparisons_with_a_percent_hint(self):
        from songselector.config import COMPLEX_SEARCH_COLUMNS
        from songselector.ui.advanced_search_dialog import AdvancedSearchRow
        self.assertIn('Match', COMPLEX_SEARCH_COLUMNS)
        row = AdvancedSearchRow(COMPLEX_SEARCH_COLUMNS)
        row.column_combo.setCurrentText('Match')
        conditions = [row.condition_combo.itemText(i) for i in range(row.condition_combo.count())]
        self.assertEqual(conditions, list(NUMERIC_COMPARISONS))
        self.assertIn('percent', row.value_edit.placeholderText())
        row.column_combo.setCurrentText('Genre')
        self.assertIn('contains', [row.condition_combo.itemText(i) for i in range(row.condition_combo.count())])

    def test_numeric_options_follow_column_selection(self):
        from songselector.ui.advanced_search_dialog import AdvancedSearchRow
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
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        from PyQt5.QtWidgets import QDialog

        from songselector.ui.advanced_search_dialog import AdvancedSearchDialog
        dialog=AdvancedSearchDialog(['Genre','Original BPM'])
        row=dialog.filter_rows[0]
        row.column_combo.setCurrentText('Original BPM')
        row.condition_combo.setCurrentText('greater than')
        row.value_edit.setText('not a number')
        dialog.show()
        with patch('songselector.ui.advanced_search_dialog.QMessageBox.warning') as warning:
            QTest.mouseClick(dialog.button_ok,Qt.LeftButton)
            self.assertEqual(dialog.result(),QDialog.Rejected)
            warning.assert_called_once()
            row.value_edit.setText('128,5')
            QTest.mouseClick(dialog.button_ok,Qt.LeftButton)
            self.assertEqual(dialog.result(),QDialog.Accepted)
        self.assertEqual(dialog.get_active_filters()[0]['value'],'128,5')
        dialog.close()

    def make_window(self):
        import pandas as pd

        from songselector.config import init_settings
        from songselector.ui.main_window import MainWindow
        init_settings()
        window=MainWindow()
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
        from songselector.config import HEADER_INDEX
        return {window.candidate_tree.topLevelItem(i).text(HEADER_INDEX['Title'])
                for i in range(window.candidate_tree.topLevelItemCount())
                if not window.candidate_tree.topLevelItem(i).isHidden()}

    def test_actual_dialog_combines_genre_and_numeric_range_and_restores_settings(self):
        from PyQt5.QtCore import QTimer

        from songselector.ui.main_window import MainWindow
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
        restored=MainWindow()
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

    def test_unticked_row_keeps_the_rule_but_leaves_it_out_of_the_search(self):
        # Asked 2026-11-27: an Active tick on every row, instead of setting the column to None.
        from PyQt5.QtCore import QTimer

        from songselector.core.search_filters import NO_COLUMN
        window=self.make_window()
        rules=[('Genre','contains','tribal'),('Original BPM','greater than','abc'),
               ('Genre','is','house')]
        def configure():
            dialog=window.advanced_search_dialog
            combo=dialog.filter_rows[0].column_combo
            self.assertNotIn(NO_COLUMN,[combo.itemText(i) for i in range(combo.count())])
            self.assertTrue(all(row.active_check.isChecked() for row in dialog.filter_rows))
            dialog.checkbox_enable.setChecked(True)
            for row,(column,condition,value) in zip(dialog.filter_rows,rules):
                row.column_combo.setCurrentText(column)
                row.condition_combo.setCurrentText(condition)
                row.value_edit.setText(value)
            # unticked: the column, the condition and even an invalid number stay, OK still works
            dialog.filter_rows[1].active_check.setChecked(False)
            dialog.filter_rows[2].active_check.setChecked(False)
            dialog.button_ok.click()
        QTimer.singleShot(0,configure)
        window.open_advanced_search()
        self.assertEqual(self.visible_titles(window),{'middle','lower','upper','unknown'})
        self.assertEqual(window.btn_advanced_search.text(),'Advanced Search (1 active)')
        self.assertEqual(len(window.current_advanced_search['filters']),3)
        seen=[]
        def inspect_restored():
            row=window.advanced_search_dialog.filter_rows[1]
            seen.append((row.active_check.isChecked(),row.column_combo.currentText(),
                         row.condition_combo.currentText(),row.value_edit.text()))
            window.advanced_search_dialog.button_cancel.click()
        QTimer.singleShot(0,inspect_restored)
        window.open_advanced_search()
        self.assertEqual(seen,[(False,'Original BPM','greater than','abc')])
        window.populate_tree()
        self.assertEqual(len(window.advanced_filters),1)
        window.close()

    def test_a_row_saved_with_the_none_column_comes_back_unticked(self):
        from songselector.core.search_filters import NO_COLUMN
        from songselector.ui.advanced_search_dialog import AdvancedSearchDialog
        dialog=AdvancedSearchDialog(['Genre','Original BPM'])
        dialog.set_filters([{'column':NO_COLUMN,'condition':'does not contain','value':'breakbeat'},
                            {'column':'Original BPM','condition':'greater than','value':'120'}])
        old,kept=dialog.filter_rows[:2]
        self.assertFalse(old.active_check.isChecked())
        self.assertEqual((old.column_combo.currentText(),old.condition_combo.currentText(),old.value_edit.text()),
                         ('Genre','does not contain','breakbeat'))
        self.assertTrue(kept.active_check.isChecked())  # saved before the tick: counts as ticked
        self.assertEqual([f['value'] for f in dialog.get_active_filters()],['120'])
        self.assertEqual(len(dialog.saved_filters()),2)
        dialog.close()

    def test_condition_boxes_are_equally_wide_whatever_the_column(self):
        # Asked 2026-11-27: Match offers only the short number comparisons and its box was narrower than the rest.
        from songselector.config import COMPLEX_SEARCH_COLUMNS
        from songselector.ui.advanced_search_dialog import AdvancedSearchDialog
        dialog=AdvancedSearchDialog(COMPLEX_SEARCH_COLUMNS)
        for row,column in zip(dialog.filter_rows,['Match','Genre','Speed change','Rating','Artist']):
            row.column_combo.setCurrentText(column)
        dialog.show()
        widths={row.condition_combo.width() for row in dialog.filter_rows}
        self.assertEqual(len(widths),1,widths)
        widest=max(dialog.filter_rows[0].fontMetrics().boundingRect(c).width()
                   for c in ['does not contain','outside ± (%)','at least (>=)'])
        self.assertGreater(widths.pop(),widest)  # the longest condition fits
        dialog.close()

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

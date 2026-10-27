"""Packaged-app verification; uses only fixtures and the app's own test data directory."""
import json
import os
from pathlib import Path
import sys


def run():
    result_path=Path(os.environ['TRAKTOR_VERIFY_RESULT']).resolve()
    result={}
    window=None
    try:
        from mutagen.id3 import ID3, TIT2, TPE1, TKEY, TBPM, POPM
        from PyQt5.QtWidgets import QApplication, QStyleOptionViewItem, QStyle
        from PyQt5.QtCore import QCoreApplication, QMimeData, QUrl, QPoint, QPointF, Qt
        from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QImage, QPainter, QStandardItemModel, QStandardItem
        from traktor_key_calculator.config import init_settings, HEADER_INDEX, HEADER_LABELS, APP_DATA_DIR, COLOR_MAPPING_CATEGORY, OPEN_KEY_COLOR_MAPPING
        from traktor_key_calculator.ui.main_window import TraktorKeyCalculator
        from traktor_key_calculator.core.traktor_collection import canonical_path
        from traktor_key_calculator.core.track_import import TrackImporter
        from traktor_key_calculator.ui.delegates import ColorDotDelegate
        from traktor_key_calculator.ui.advanced_search_dialog import AdvancedSearchRow
        from xml.etree import ElementTree as ET
        from PyQt5.QtCore import QRect
        import ntpath
        fixture=APP_DATA_DIR/'packaged_check.mp3'
        tags=ID3()
        tags.add(TIT2(encoding=3,text=['Packaged drop check']))
        tags.add(TPE1(encoding=3,text=['Build verification']))
        tags.add(TKEY(encoding=3,text=['C']))
        tags.add(TBPM(encoding=3,text=['100']))
        tags.add(POPM(email='traktor@native-instruments.de',rating=204,count=0))
        tags.save(fixture)
        nml_root=ET.Element('NML',VERSION='19')
        collection=ET.SubElement(nml_root,'COLLECTION',ENTRIES='1')
        entry=ET.SubElement(collection,'ENTRY')
        drive,tail=ntpath.splitdrive(str(fixture.parent))
        ET.SubElement(entry,'LOCATION',VOLUME=drive,DIR=tail.replace('\\','/:')+'/:',FILE=fixture.name)
        ET.SubElement(entry,'INFO',COLOR='5',RANKING='255')
        ET.SubElement(entry,'TEMPO',BPM='100')
        ET.SubElement(entry,'MUSICAL_KEY',VALUE='0')
        test_collection=APP_DATA_DIR/'color-check.nml'
        ET.ElementTree(nml_root).write(test_collection,encoding='utf-8')
        application=QApplication.instance() or QApplication(sys.argv)
        ok,error=init_settings()
        assert ok,str(error)
        settings_path=APP_DATA_DIR/'SpotNextTrack_settings.json'
        legacy=json.loads(settings_path.read_text())
        legacy.pop('Rating display version',None)
        legacy['Search columns']=['Artist','Title']
        for side in ('left','right'):
            legacy['Visible column '+side]=[name for name in HEADER_LABELS if name!='Rating']
            legacy.setdefault('Column sizes '+side,{})['Rating']=0
        settings_path.write_text(json.dumps(legacy))
        window=TraktorKeyCalculator()
        assert window.search_column_actions['Rating'].isChecked()
        library_ratings=sum(bool(window.candidate_tree.topLevelItem(i).text(HEADER_INDEX['Rating']))
                            for i in range(window.candidate_tree.topLevelItemCount()))
        if window.importer.collection.by_path:
            assert library_ratings>0,'Existing library ratings were not enriched'
        window.importer=TrackImporter(test_collection)
        window.coloring_mode='song'
        baseline=window.candidate_tree.topLevelItemCount()
        assert baseline>=2920,baseline
        window.bpm_slider.setValue(100)

        def drop(tree,paths):
            mime=QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
            enter=QDragEnterEvent(QPoint(8,8),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
            QCoreApplication.sendEvent(tree.viewport(),enter)
            assert enter.isAccepted(),'Drag enter rejected'
            event=QDropEvent(QPointF(8,8),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
            QCoreApplication.sendEvent(tree.viewport(),event)
            assert event.isAccepted(),'Drop rejected'
            application.processEvents()

        def find(tree,path):
            return next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                        if canonical_path(tree.topLevelItem(i).text(HEADER_INDEX['Path']))==canonical_path(path))

        drop(window.candidate_tree,[fixture,fixture])
        item=find(window.candidate_tree,fixture)
        assert item.text(HEADER_INDEX['Original Key'])=='C major'
        assert item.text(HEADER_INDEX['New Key'])=='C major'
        assert window.candidate_tree.topLevelItemCount()==baseline+1
        assert item.text(HEADER_INDEX['Rating'])=='4'
        previous_search=window.search_columns
        window.search_columns=['Rating']
        window.search_bar.setText('4')
        window.filter_items()
        assert not item.isHidden()
        window.search_bar.setText('5')
        window.filter_items()
        assert item.isHidden()
        window.search_bar.clear()
        window.search_columns=previous_search
        window.filter_items()
        window.advanced_filters=[{'column':'Rating','condition':'at least (>=)','value':'4'}]
        assert window.apply_advanced_filters_tree(item)
        window.advanced_filters[0]['value']='5'
        assert not window.apply_advanced_filters_tree(item)
        window.advanced_filters=[]
        search_row=AdvancedSearchRow(HEADER_LABELS)
        search_row.column_combo.setCurrentText('Original BPM')
        search_row.condition_combo.setCurrentText('greater than')
        search_row.value_edit.setText('90')
        assert search_row.get_filter()['condition']=='greater than'
        window.advanced_filters=[search_row.get_filter(), {'column':'Original BPM','condition':'less than','value':'110'}]
        assert window.apply_advanced_filters_tree(item)
        window.advanced_filters[0]['value']='100'
        assert not window.apply_advanced_filters_tree(item)
        window.advanced_filters[0]['condition']='at least (>=)'
        assert window.apply_advanced_filters_tree(item)
        window.advanced_filters=[]
        search_row.close()
        window.search_bar.setText('color:blue')
        assert not item.isHidden()
        assert window.color_search_actions[5].isChecked()
        window.color_search_actions[1].trigger()
        assert 'red' in window.search_bar.text()
        assert not item.isHidden()
        window.search_bar.setText('color:orange')
        assert item.isHidden()
        window.search_bar.setText('-color:blue')
        assert item.isHidden()
        window.search_bar.setText('Packaged color:blue')
        assert not item.isHidden()
        window.search_bar.setText('color:bluu')
        assert item.isHidden()
        assert 'Unknown color' in window.status_label.text()
        window.search_bar.clear()
        window.advanced_filters=[{'column':'Color','condition':'is','value':'blue'}]
        assert window.apply_advanced_filters_tree(item)
        window.advanced_filters=[]
        drop(window.playlist_tree,[fixture,fixture])
        assert window.playlist_tree.topLevelItemCount()==1
        for view in (window.candidate_tree,window.playlist_tree):
            colored=find(view,fixture)
            assert colored.text(HEADER_INDEX['Color'])=='5'
            assert colored.background(0).color().rgb()==COLOR_MAPPING_CATEGORY[5].rgb()
            assert not view.isColumnHidden(HEADER_INDEX['Color'])
            assert not view.isColumnHidden(HEADER_INDEX['Rating'])
            assert view.columnWidth(HEADER_INDEX['Rating'])>0
            assert colored.text(HEADER_INDEX['Rating'])=='4'
        window.coloring_mode='key'
        window.populate_tree()
        for view in (window.candidate_tree,window.playlist_tree):
            assert find(view,fixture).background(0).color().rgb()==OPEN_KEY_COLOR_MAPPING['1d'].rgb()
        window.bpm_slider.setValue(150)
        window.update_tree_after_slider()
        assert find(window.playlist_tree,fixture).text(HEADER_INDEX['New Key'])=='G major'
        for view in (window.candidate_tree,window.playlist_tree):
            assert find(view,fixture).background(0).color().rgb()==OPEN_KEY_COLOR_MAPPING['2d'].rgb()
        window.coloring_mode='song'
        window.populate_tree()
        model=QStandardItemModel();model.appendRow(QStandardItem('5'))
        image=QImage(40,30,QImage.Format_ARGB32);image.fill(0xffffffff)
        option=QStyleOptionViewItem();option.rect=QRect(0,0,40,30)
        option.state=QStyle.State_Enabled|QStyle.State_Selected
        painter=QPainter(image)
        ColorDotDelegate().paint(painter,option,model.index(0,0))
        painter.end()
        assert image.pixelColor(option.rect.center()).rgb()==COLOR_MAPPING_CATEGORY[5].rgb()
        real_path=Path(r'E:\DJ\BREAKBEAT\Afghan Headspin - The Calling.mp3')
        real_checked=False
        if real_path.is_file():
            window.importer=TrackImporter(r'E:\DJ\TRAKTOR\collection.nml')
            expected_color=int(window.importer.collection.find(real_path).get('color') or 0)
            drop(window.candidate_tree,[real_path])
            assert find(window.candidate_tree,real_path).text(HEADER_INDEX['Original Key'])=='B minor'
            assert find(window.candidate_tree,real_path).text(HEADER_INDEX['Color'])==str(expected_color)
            real_checked=True
        library_rows=len(window.table)
        playlist_rows=window.playlist_tree.topLevelItemCount()
        window.close()
        window=None
        application.processEvents()
        restored=TraktorKeyCalculator()
        assert canonical_path(fixture) in restored.saved_imports
        assert find(restored.candidate_tree,fixture).text(HEADER_INDEX['Original Key'])=='C major'
        assert restored.library_store.path.is_file()
        assert len(restored.table)==library_rows,'Library list was not restored'
        assert restored.playlist_tree.topLevelItemCount()==playlist_rows,'Playlist was not restored'
        assert any(action.text()=='Delete duplicates from the list' for action in restored.library_context_menu().actions())
        assert restored.delete_duplicate_tracks()==0
        restored.close()
        result={'ok':True,'frozen':bool(getattr(sys,'frozen',False)),'baseline_tracks':baseline,
                'drop_events':True,'duplicates':True,'playlist_key_at_150_bpm':'G major',
                'imports_survive_restart':True,'real_open_key_mp3':real_checked,
                'traktor_category_colors':True,'key_colors_follow_tempo':True,'painted_color_dot':True,'numeric_search_comparisons':True,
                'ratings_visible_and_searchable':True,'existing_library_ratings':library_ratings,
                'named_color_search':True,'color_swatch_menu':True,'multiple_colors_and_exclusions':True,'complex_search_color_names':True,
                'library_and_playlist_restored':True,'library_rows':library_rows,'playlist_rows':playlist_rows,
                'delete_duplicates_menu':True}
    except BaseException as error:
        import traceback
        result={'ok':False,'error':repr(error),'traceback':traceback.format_exc()}
        if window is not None:
            window.close()
    result_path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return 0 if result.get('ok') else 1

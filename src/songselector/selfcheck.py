"""Packaged-app verification; uses only fixtures and the app's own test data directory."""
import json
import os
import sys
from pathlib import Path


def _check_embedding_process():
    """With SONGSELECTOR_VERIFY_MODEL set to cnn14.onnx: analyse a generated 11 s tone in the
    analysis process, which proves multiprocessing, onnxruntime, soundfile and soxr work
    inside the frozen exe. Returns a summary, or 'skipped' without a model."""
    model=os.environ.get('SONGSELECTOR_VERIFY_MODEL')
    if not model:
        return 'skipped (set SONGSELECTOR_VERIFY_MODEL to cnn14.onnx)'
    import numpy as np
    import soundfile

    from songselector.config import APP_DATA_DIR
    from songselector.core.embeddings import EmbeddingStore
    from songselector.core.traktor_collection import canonical_path
    from songselector.ui.embedding_worker import EmbeddingAnalyzer
    tone=APP_DATA_DIR/'embedding_check.wav'
    seconds=np.arange(11*44100)/44100
    soundfile.write(str(tone),np.stack([0.3*np.sin(2*np.pi*440*seconds)]*2,axis=1),44100)
    store=EmbeddingStore(APP_DATA_DIR/'embedding_check.sqlite')
    analyzer=EmbeddingAnalyzer(store,model)
    analyzer.submit([(canonical_path(tone),str(tone))])
    analyzer.start()
    try:
        assert analyzer.wait_idle(180),'Embedding analysis did not finish'
    finally:
        analyzer.stop()
    matrix=store.load(canonical_path(tone))
    assert matrix is not None and matrix.shape==(3,2048),f'Unexpected embedding: {None if matrix is None else matrix.shape}'
    return f'ok, {matrix.shape[0]}x{matrix.shape[1]} on {analyzer.device}'


def _check_aac_decoding():
    """Writes a short AAC (.m4a) file with FFmpeg and decodes it with the app's loader: proves the
    FFmpeg libraries (PyAV) are in the exe and that the fallback after libsndfile works."""
    import av
    import numpy as np

    from songselector.config import APP_DATA_DIR
    from songselector.core.embeddings import SAMPLE_RATE, load_audio
    path=APP_DATA_DIR/'aac_check.m4a'
    seconds=np.arange(4*44100)/44100
    tone=(0.3*np.sin(2*np.pi*440*seconds)).astype(np.float32)
    with av.open(str(path),'w',format='ipod') as container:
        stream=container.add_stream('aac',rate=44100)
        stream.layout='stereo'
        frame=av.AudioFrame.from_ndarray(np.stack([tone,tone]),format='fltp',layout='stereo')
        frame.sample_rate=44100
        for packet in stream.encode(frame)+stream.encode(None):
            container.mux(packet)
    audio=load_audio(path)
    path.unlink()
    assert abs(len(audio)/SAMPLE_RATE-4)<0.2,f'Decoded {len(audio)/SAMPLE_RATE:.2f} s of a 4 s AAC file'
    assert abs(float(np.sqrt((audio**2).mean()))-0.3/2**0.5)<0.03,'AAC file decoded at the wrong level'
    return 'ok'


def _check_rekordbox_reader():
    """Writes a small encrypted library like Rekordbox's master.db and reads its playlists with
    the app's own reader: proves the SQLCipher module and the key work inside the frozen exe."""
    from sqlcipher3 import dbapi2 as sqlcipher

    from songselector.config import APP_DATA_DIR
    from songselector.core.rekordbox_library import RekordboxLibrary, database_key
    path=APP_DATA_DIR/'rekordbox_check.db'
    path.unlink(missing_ok=True)
    connection=sqlcipher.connect(str(path))
    connection.execute(f"PRAGMA key='{database_key()}'")
    connection.execute('CREATE TABLE djmdPlaylist (ID, Seq, Name, Attribute, ParentID, SmartList, rb_local_deleted)')
    connection.execute('CREATE TABLE djmdSongPlaylist (PlaylistID, ContentID, TrackNo, rb_local_deleted)')
    connection.execute('CREATE TABLE djmdContent (ID, FolderPath, rb_local_deleted)')
    connection.execute("INSERT INTO djmdPlaylist VALUES ('1', 1, 'Set', 0, 'root', NULL, 0)")
    connection.executemany('INSERT INTO djmdContent VALUES (?, ?, 0)', [('10', 'E:/DJ/a.mp3'), ('11', 'E:/DJ/b.mp3')])
    connection.executemany("INSERT INTO djmdSongPlaylist VALUES ('1', ?, ?, 0)", [('11', 1), ('10', 2)])
    connection.commit()
    connection.close()
    library=RekordboxLibrary(str(path))
    library._load()
    assert not library.error,library.error
    assert library.playlists==[{'type':'PLAYLIST','name':'Set','tracks':[r'E:\DJ\b.mp3',r'E:\DJ\a.mp3']}],library.playlists
    path.unlink()
    return 'ok'


def run():
    result_path=Path(os.environ['SONGSELECTOR_VERIFY_RESULT']).resolve()
    result={}
    window=None
    try:
        import ntpath
        from xml.etree import ElementTree as ET

        from mutagen.id3 import ID3, POPM, TBPM, TIT2, TKEY, TPE1
        from PyQt5.QtCore import QCoreApplication, QMimeData, QPoint, QPointF, QRect, Qt, QUrl
        from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QImage, QPainter, QStandardItem, QStandardItemModel
        from PyQt5.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

        from songselector.config import (
            APP_DATA_DIR,
            COLOR_MAPPING_CATEGORY,
            HEADER_INDEX,
            HEADER_LABELS,
            OPEN_KEY_COLOR_MAPPING,
            SETTINGS_FILE,
            init_settings,
        )
        from songselector.core.track_import import TrackImporter
        from songselector.core.traktor_collection import canonical_path
        from songselector.ui.advanced_search_dialog import AdvancedSearchRow
        from songselector.ui.delegates import ColorDotDelegate
        from songselector.ui.main_window import MainWindow
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
        settings_path=Path(SETTINGS_FILE)
        legacy=json.loads(settings_path.read_text())
        legacy.pop('Rating display version',None)
        legacy['Search columns']=['Artist','Title']
        for side in ('left','right'):
            legacy['Visible column '+side]=[name for name in HEADER_LABELS if name!='Rating']
            legacy.setdefault('Column sizes '+side,{})['Rating']=0
        settings_path.write_text(json.dumps(legacy))
        window=MainWindow()
        assert window.search_column_actions['Rating'].isChecked()
        baseline=window.candidate_tree.topLevelItemCount()
        assert baseline==0,f'A fresh install must start with an empty library, found {baseline} tracks'
        window.importer=TrackImporter(test_collection)
        window.coloring_mode='song'
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
        model=QStandardItemModel()
        model.appendRow(QStandardItem('5'))
        image=QImage(40,30,QImage.Format_ARGB32)
        image.fill(0xffffffff)
        option=QStyleOptionViewItem()
        option.rect=QRect(0,0,40,30)
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
        restored=MainWindow()
        assert canonical_path(fixture) in restored.saved_imports
        assert find(restored.candidate_tree,fixture).text(HEADER_INDEX['Original Key'])=='C major'
        assert restored.library_store.path.is_file()
        assert len(restored.table)==library_rows,'Library list was not restored'
        assert restored.playlist_tree.topLevelItemCount()==playlist_rows,'Playlist was not restored'
        assert any(action.text()=='Delete duplicates from the list' for action in restored.library_context_menu().actions())
        assert restored.delete_duplicate_tracks()==0
        restored.close()
        rekordbox=_check_rekordbox_reader()
        aac=_check_aac_decoding()
        embedding=_check_embedding_process()
        result={'ok':True,'frozen':bool(getattr(sys,'frozen',False)),'baseline_tracks':baseline,
                'drop_events':True,'duplicates':True,'playlist_key_at_150_bpm':'G major',
                'imports_survive_restart':True,'real_open_key_mp3':real_checked,
                'traktor_category_colors':True,'key_colors_follow_tempo':True,'painted_color_dot':True,'numeric_search_comparisons':True,
                'ratings_visible_and_searchable':True,
                'named_color_search':True,'color_swatch_menu':True,'multiple_colors_and_exclusions':True,'complex_search_color_names':True,
                'library_and_playlist_restored':True,'library_rows':library_rows,'playlist_rows':playlist_rows,
                'delete_duplicates_menu':True,'rekordbox_reader':rekordbox,'aac_decoding':aac,'embedding_process':embedding}
    except BaseException as error:
        import traceback
        result={'ok':False,'error':repr(error),'traceback':traceback.format_exc()}
        if window is not None:
            window.close()
    result_path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return 0 if result.get('ok') else 1

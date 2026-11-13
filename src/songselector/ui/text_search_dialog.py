"""Search by description: type what a track should sound like, get the closest tracks (CLAP models).

The prompt goes to the text search process (ui/text_search_worker.py), which returns a vector in the same space as
the tracks' audio vectors; the tracks are ranked by cosine similarity (core/text_search.py). Only tracks analysed
with the chosen model can be found.
"""
import threading
import time

from PyQt5.QtCore import QMimeData, QObject, Qt, QUrl, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from songselector.core.text_search import clap_track_vector, rank
from songselector.ui.text_search_worker import TextSearchWorker

RESULT_COLUMNS = ['#', 'Score', 'Artist', 'Title', 'Genre', 'BPM', 'Key']
FIELD_FOR_COLUMN = {'Artist': 'Artist', 'Title': 'Title', 'Genre': 'Genre', 'BPM': 'Original BPM', 'Key': 'Original Key'}
EXAMPLE = 'e.g. funky breakbeat with a groovy bassline and chopped drum breaks'


def load_track_vectors(store):
    """(keys, unit vectors) of every track the store's model has analysed: the average of its windows."""
    import numpy as np
    matrices = store.load_many()
    keys = sorted(matrices)
    if not keys:
        return [], np.zeros((0, store.spec.dim), dtype=np.float32)
    return keys, np.stack([clap_track_vector(matrices[key].astype(np.float32)) for key in keys])


class _Loaded(QObject):
    done = pyqtSignal(str, object)   # model id, (keys, vectors) or an exception


class ResultsTree(QTreeWidget):
    """Results; dragging them out gives their files (onto a Traktor deck, a playlist, Explorer)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(RESULT_COLUMNS)
        self.setRootIsDecorated(False)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setAlternatingRowColors(True)

    def mimeData(self, items):
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(item.data(0, Qt.UserRole + 1)) for item in items
                      if item.data(0, Qt.UserRole + 1)])
        return data


class TextSearchDialog(QDialog):
    def __init__(self, models, stores, models_folder, settings, fields_provider, select_track, add_to_playlist,
                 worker=None, parent=None):
        """models: CLAP EmbeddingModels that can be searched; stores: {model id: EmbeddingStore}.
        fields_provider(key) -> {column: text} or None for tracks not in the library or playlist.
        select_track(key), add_to_playlist(keys): actions in the main window."""
        super().__init__(parent)
        self.setWindowTitle('Search by description')
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint)
        self.resize(1000, 560)
        self.models, self.stores, self.settings = models, stores, settings
        self.fields_provider, self.select_track, self.add_to_playlist = fields_provider, select_track, add_to_playlist
        self.worker = worker or TextSearchWorker(models_folder, parent=self)
        self.worker.vector_ready.connect(self._vector_ready)
        self.worker.failed.connect(self._failed)
        self._vectors = {}        # model id -> (keys, vectors)
        self._loading = set()     # model ids being loaded
        self._stale = set()       # model ids with newly analysed tracks since loading
        self._pending = None      # (request id, model id, prompt, started)
        self._query = None        # (model id, vector, prompt, seconds) of the last answer
        self._loader = _Loaded()
        self._loader.done.connect(self._vectors_loaded)
        self._build()
        self._load_vectors(self.model_id())

    # -- layout ------------------------------------------------------------------------------------------

    def _build(self):
        self.model_box = QComboBox()
        for spec in self.models:
            self.model_box.addItem(spec.name, spec.id)
            self.model_box.setItemData(self.model_box.count() - 1, spec.description, Qt.ToolTipRole)
        chosen = self.model_box.findData(self.settings.get('Text search model'))
        if chosen >= 0:
            self.model_box.setCurrentIndex(chosen)
        self.model_box.currentIndexChanged.connect(self._model_changed)
        self.prompt = QLineEdit()
        self.prompt.setPlaceholderText(EXAMPLE)
        self.prompt.returnPressed.connect(self.search)
        self.search_button = QPushButton('Search')
        self.search_button.setDefault(True)
        self.search_button.clicked.connect(self.search)
        self.count = QSpinBox()
        self.count.setRange(5, 200)
        self.count.setValue(int(self.settings.get('Text search results', 10)))
        self.count.setPrefix('Top ')
        self.count.valueChanged.connect(self._count_changed)
        top = QHBoxLayout()
        top.addWidget(QLabel('Model'))
        top.addWidget(self.model_box)
        top.addWidget(self.prompt, 1)
        top.addWidget(self.search_button)
        top.addWidget(self.count)

        self.saved = QListWidget()
        self.saved.addItems(self.settings.get('Saved prompts', []))
        self.saved.itemClicked.connect(lambda item: self._use_prompt(item.text()))
        self.saved.setToolTip('Click a saved prompt to search with it')
        save = QPushButton('Save prompt')
        save.clicked.connect(self.save_prompt)
        remove = QPushButton('Remove')
        remove.clicked.connect(self.remove_prompt)
        saved_buttons = QHBoxLayout()
        saved_buttons.addWidget(save)
        saved_buttons.addWidget(remove)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel('Saved prompts'))
        left_layout.addWidget(self.saved, 1)
        left_layout.addLayout(saved_buttons)

        self.results = ResultsTree()
        self.results.itemDoubleClicked.connect(lambda item, _column: self.select_track(item.data(0, Qt.UserRole)))
        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.results)
        splitter.setSizes([230, 770])

        self.status = QLabel()
        self.status.setWordWrap(True)
        add = QPushButton('Add selected to playlist')
        add.clicked.connect(self._add_selected)
        close = QPushButton('Close')
        close.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.addWidget(self.status, 1)
        bottom.addWidget(add)
        bottom.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)
        layout.addLayout(bottom)
        hint = QLabel('Describe the sound: instruments, textures, energy and mood ("warm pads, slow and dreamy"). '
                      'Double-click a result to select it in the list; drag results onto Traktor.')
        hint.setWordWrap(True)
        hint.setStyleSheet('color: gray')
        layout.addWidget(hint)

    # -- data --------------------------------------------------------------------------------------------

    def model_id(self):
        return self.model_box.currentData()

    def mark_stale(self):
        """New tracks were analysed: reload the vectors before the next search."""
        self._stale.update(self._vectors)

    def _load_vectors(self, model_id):
        if model_id is None or model_id in self._loading:
            return
        self._loading.add(model_id)
        self._stale.discard(model_id)
        self._show_status()
        store = self.stores[model_id]

        def work():
            try:
                result = load_track_vectors(store)
            except Exception as error:  # e.g. the cache is busy: report it, try again with the next search
                result = error
            self._loader.done.emit(model_id, result)
        threading.Thread(target=work, name='text-search-vectors', daemon=True).start()

    def _vectors_loaded(self, model_id, result):
        self._loading.discard(model_id)
        if isinstance(result, Exception):
            self.status.setText(f'Could not read the analysed tracks: {result}')
            return
        self._vectors[model_id] = result
        self._show_results()

    def _model_changed(self):
        self.settings['Text search model'] = self.model_id()
        if self.model_id() not in self._vectors:
            self._load_vectors(self.model_id())
        if self.prompt.text().strip():
            self.search()

    def _count_changed(self, value):
        self.settings['Text search results'] = value
        self._show_results()

    # -- searching ---------------------------------------------------------------------------------------

    def search(self):
        prompt = self.prompt.text().strip()
        model_id = self.model_id()
        if not prompt or model_id is None:
            return
        if model_id in self._stale or (model_id not in self._vectors and model_id not in self._loading):
            self._load_vectors(model_id)
        request = self.worker.query(model_id, prompt)
        self._pending = (request, model_id, prompt, time.perf_counter())
        self._show_status()

    def _vector_ready(self, request_id, vector):
        if self._pending is None or self._pending[0] != request_id:
            return  # an answer to an older search
        _request, model_id, prompt, started = self._pending
        self._pending = None
        self._query = (model_id, vector, prompt, time.perf_counter() - started)
        self._show_results()

    def _failed(self, request_id, message):
        if request_id and (self._pending is None or self._pending[0] != request_id):
            return
        self._pending = None
        self.status.setText(f'Search failed: {message}')

    def _show_results(self):
        if self._query is None or self._query[0] not in self._vectors:
            self._show_status()
            return
        model_id, vector, prompt, seconds = self._query
        keys, vectors = self._vectors[model_id]
        self.results.clear()
        shown = 0
        for key, score in rank(vector, keys, vectors):
            fields = self.fields_provider(key)
            if fields is None:
                continue  # analysed earlier, but no longer in the library
            shown += 1
            values = [str(shown), f'{score:.3f}'] + [fields.get(FIELD_FOR_COLUMN[name], '') for name in RESULT_COLUMNS[2:]]
            item = QTreeWidgetItem(values)
            item.setData(0, Qt.UserRole, key)
            item.setData(0, Qt.UserRole + 1, fields.get('Path', ''))
            self.results.addTopLevelItem(item)
            if shown >= self.count.value():
                break
        for column in range(len(RESULT_COLUMNS)):
            self.results.resizeColumnToContents(column)
        self._show_status(f'"{prompt}": text encoded in {seconds * 1000:.0f} ms')

    def _show_status(self, extra=''):
        model_id = self.model_id()
        name = self.model_box.currentText()
        if model_id in self._loading:
            text = f'Loading the tracks analysed with {name}...'
        elif model_id in self._vectors:
            count = len(self._vectors[model_id][0])
            text = (f'{count:,} tracks analysed with {name}.' if count else
                    f'No tracks analysed with {name} yet: switch it on under Analysis -> Embedding models.')
        else:
            text = ''
        if self._pending is not None:
            text += ' Searching... (the first search loads the text model, a few seconds)'
        elif extra:
            text += f' {extra}.'
        self.status.setText(text.strip())

    # -- prompts and actions -----------------------------------------------------------------------------

    def _use_prompt(self, text):
        self.prompt.setText(text)
        self.search()

    def save_prompt(self):
        text = self.prompt.text().strip()
        prompts = list(self.settings.get('Saved prompts', []))
        if text and text not in prompts:
            prompts.append(text)
            self.settings['Saved prompts'] = prompts
            self.saved.addItem(text)

    def remove_prompt(self):
        item = self.saved.currentItem()
        if item is None:
            return
        self.settings['Saved prompts'] = [p for p in self.settings.get('Saved prompts', []) if p != item.text()]
        self.saved.takeItem(self.saved.row(item))

    def _add_selected(self):
        keys = [item.data(0, Qt.UserRole) for item in self.results.selectedItems()]
        if keys:
            self.add_to_playlist(keys)

    def closeEvent(self, event):
        self.worker.stop(timeout=1)  # frees the text model's memory
        super().closeEvent(event)

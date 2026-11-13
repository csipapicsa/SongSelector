"""Free-text search for the main window's description bar: prompt in, ranked tracks out (CLAP models).

Holds the text search process (ui/text_search_worker.py) and each model's track vectors, loaded in a thread and
reloaded after new tracks were analysed. One answer per search: the latest prompt wins.
"""
import threading
import time

from PyQt5.QtCore import QObject, pyqtSignal

from songselector.core.text_search import rank
from songselector.ui.text_search_dialog import load_track_vectors
from songselector.ui.text_search_worker import TextSearchWorker


class TextSearchEngine(QObject):
    results = pyqtSignal(str, list, float)   # prompt, [(path_key, score)] best first, seconds for the text
    status = pyqtSignal(str)                 # what is happening ('' when idle)
    failed = pyqtSignal(str)
    _loaded = pyqtSignal(str, object)        # model id, (keys, vectors) or an exception (from the loading thread)

    def __init__(self, stores, models_folder, worker=None, parent=None):
        super().__init__(parent)
        self.stores = stores
        self.worker = worker or TextSearchWorker(models_folder, parent=self)
        self.worker.vector_ready.connect(self._vector_ready)
        self.worker.failed.connect(self._failed)
        self._vectors, self._loading, self._stale = {}, set(), set()
        self._pending = None      # (request id, model id, prompt, started)
        self._answer = None       # (model id, prompt, vector, seconds) waiting for the vectors
        self._loaded.connect(self._vectors_loaded)

    def analysed_count(self, model_id):
        return len(self._vectors[model_id][0]) if model_id in self._vectors else None

    def mark_stale(self):
        self._stale.update(self._vectors)

    def search(self, model_id, prompt):
        if model_id in self._stale or (model_id not in self._vectors and model_id not in self._loading):
            self._load(model_id)
        self._pending = (self.worker.query(model_id, prompt), model_id, prompt, time.perf_counter())
        self._answer = None
        self.status.emit('Searching... (the first search loads the text model, a few seconds)')

    def _load(self, model_id):
        if model_id in self._loading:
            return
        self._loading.add(model_id)
        self._stale.discard(model_id)
        store = self.stores[model_id]

        def work():
            try:
                result = load_track_vectors(store)
            except Exception as error:  # the cache is busy, for example
                result = error
            self._loaded.emit(model_id, result)
        threading.Thread(target=work, name='text-search-vectors', daemon=True).start()

    def _vectors_loaded(self, model_id, result):
        self._loading.discard(model_id)
        if isinstance(result, Exception):
            self.failed.emit(f'Could not read the analysed tracks: {result}')
            return
        self._vectors[model_id] = result
        self._deliver()

    def _vector_ready(self, request_id, vector):
        if self._pending is None or self._pending[0] != request_id:
            return  # an answer to an older search
        _request, model_id, prompt, started = self._pending
        self._pending = None
        self._answer = (model_id, prompt, vector, time.perf_counter() - started)
        self._deliver()

    def _deliver(self):
        if self._answer is None or self._answer[0] not in self._vectors:
            return
        model_id, prompt, vector, seconds = self._answer
        self._answer = None
        keys, vectors = self._vectors[model_id]
        self.status.emit('')
        self.results.emit(prompt, rank(vector, keys, vectors), seconds)

    def _failed(self, request_id, message):
        if request_id and (self._pending is None or self._pending[0] != request_id):
            return
        self._pending = None
        self.failed.emit(message)

    def stop(self):
        self.worker.stop(timeout=1)

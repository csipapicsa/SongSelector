"""Turns typed descriptions into CLAP text vectors in a background process (see core/text_search.py).

A process, like the embedding analysis: onnxruntime must not load next to PyQt5, and the text encoders are large
(~500 MB each), so the app only pays for them while the search window is in use. Started on the first query,
stopped when the window closes.
"""
import itertools
import multiprocessing
import queue

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from songselector.core.text_search import TextEncoder, run_text_encoder

POLL_INTERVAL_MS = 50


class TextSearchWorker(QObject):
    vector_ready = pyqtSignal(int, object)   # request id, unit vector (numpy)
    failed = pyqtSignal(int, str)            # request id, error text

    def __init__(self, models_folder, encoder_factory=TextEncoder, parent=None):
        super().__init__(parent)
        self.folder = str(models_folder)
        self.encoder_factory = encoder_factory  # picklable (module-level); tests pass a fake
        self._context = multiprocessing.get_context('spawn')
        self._process = None
        self._requests = self._responses = self._stop = None
        self._ids = itertools.count(1)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    @property
    def running(self):
        return self._process is not None and self._process.is_alive()

    def query(self, model_id, text):
        """Ask for the vector of `text`; the answer comes as vector_ready (or failed) with the returned id."""
        if not self.running:
            self._start()
        request_id = next(self._ids)
        self._requests.put((request_id, model_id, text))
        return request_id

    def _start(self):
        self._requests, self._responses, self._stop = (self._context.Queue(), self._context.Queue(),
                                                       self._context.Event())
        self._process = self._context.Process(target=run_text_encoder, name='text-search', daemon=True,
                                              args=(self.folder, self._requests, self._responses, self._stop,
                                                    self.encoder_factory))
        self._process.start()
        self._timer.start(POLL_INTERVAL_MS)

    def _poll(self):
        while self._responses is not None:
            try:
                request_id, vector, error = self._responses.get_nowait()
            except (queue.Empty, OSError, ValueError):
                break
            if error:
                self.failed.emit(request_id, error)
            else:
                self.vector_ready.emit(request_id, vector)
        if self._process is not None and not self._process.is_alive() and not self._stop.is_set():
            self._end()
            self.failed.emit(0, 'The text search process stopped unexpectedly; it restarts with the next search.')

    def stop(self, timeout=2.0):
        if self._process is None:
            return
        self._stop.set()
        self._process.join(timeout)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(1)
        self._end()

    def _end(self):
        self._timer.stop()
        for channel in (self._requests, self._responses):
            channel.cancel_join_thread()
            channel.close()
        self._process = None

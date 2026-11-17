"""Small updates off the UI thread: writing tags into a file, saving one changed row.

A single worker thread runs the jobs one after another, in the order they were submitted, so two edits of the
same file can never overtake each other. Each job's result (or exception) comes back on the UI thread, where the
callbacks update the window. The window stays responsive while a slow disk (or the background analysis) makes a
write take seconds.

Rules for jobs: no Qt widgets (they belong to the UI thread); open their own database connections (LibraryStore
and EmbeddingStore do that on every call); take their inputs as arguments captured at submit time, not from the
window's state, which may change before the job runs.
"""
import queue
import threading
import time

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication


class BackgroundWriter(QObject):
    busy_changed = pyqtSignal(bool)                # True when the first job is submitted, False when all are done
    failed = pyqtSignal(object)                    # exception of a job submitted without an on_error callback
    _finished = pyqtSignal(object, object, object)  # (on_done, on_error), result, exception: worker -> UI thread

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs = queue.Queue()
        self._pending = 0  # submitted and not yet delivered; touched on the UI thread only
        # Emitted from the worker thread, received by this object's (the UI) thread: Qt queues the call.
        self._finished.connect(self._deliver)
        self._thread = threading.Thread(target=self._run, name='background-writer', daemon=True)
        self._thread.start()

    def submit(self, job, on_done=None, on_error=None):
        """Run job() on the worker thread; then on_done(result) or on_error(exception) on the UI thread."""
        self._pending += 1
        if self._pending == 1:
            self.busy_changed.emit(True)
        self._jobs.put((job, on_done, on_error))

    def busy(self):
        return self._pending > 0

    def flush(self, timeout=30.0):
        """Wait (handling events, so the callbacks run) until every submitted job is done; False on timeout.
        For closing the window and for tests."""
        deadline = time.monotonic() + timeout
        while self._pending and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.005)
        QApplication.processEvents()
        return not self._pending

    def stop(self):
        self._jobs.put(None)

    def _run(self):
        while True:
            item = self._jobs.get()
            if item is None:
                return
            job, on_done, on_error = item
            try:
                result, error = job(), None
            except Exception as exception:  # handed to the UI thread, never lost in the worker
                result, error = None, exception
            self._finished.emit((on_done, on_error), result, error)

    def _deliver(self, callbacks, result, error):
        on_done, on_error = callbacks
        try:
            if error is None:
                if on_done is not None:
                    on_done(result)
            elif on_error is not None:
                on_error(error)
            else:
                self.failed.emit(error)
        finally:
            self._pending -= 1
            if not self._pending:
                self.busy_changed.emit(False)

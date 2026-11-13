"""Runs embedding analysis in a background process and reports progress to the UI.

Why a process and not a thread (see core/embeddings.py): onnxruntime crashes when
it loads after PyQt5 in the same process, and a decoder crash on a broken file
must not close the app. The process writes results to embeddings.sqlite itself.
This object only hands it jobs and turns its events into Qt signals.
"""
import multiprocessing
import queue
import sqlite3
import time
from collections import deque
from pathlib import Path

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from songselector.core.embeddings import Cnn14Embedder, file_fingerprint, run_analysis

MAX_CRASHES = 3          # consecutive crashes before giving up (e.g. a broken model or runtime)
POLL_INTERVAL_MS = 200
IN_FLIGHT = 4            # jobs handed to the process ahead of time
DEVICE_NAMES = {'CUDAExecutionProvider': 'GPU (CUDA)', 'DmlExecutionProvider': 'GPU (DirectML)',
                'CPUExecutionProvider': 'CPU'}


class EmbeddingAnalyzer(QObject):
    # done, total, missing files, file name being analysed ('' when idle)
    progress = pyqtSignal(int, int, int, str)
    track_analyzed = pyqtSignal(str)   # path_key
    failed = pyqtSignal(str)           # analysis stopped and will not continue by itself

    def __init__(self, store, model_path, embedder_factory=Cnn14Embedder, parent=None):
        super().__init__(parent)
        self.store = store
        self.model_path = Path(model_path)
        self.embedder_factory = embedder_factory  # must be picklable (a module-level class)
        self._context = multiprocessing.get_context('spawn')
        self._process = None
        self._jobs = self._events = self._stop = None
        self._submitted = {}      # path_key -> file path, in submission order
        self._finished = set()
        # Jobs go to the process a few at a time: a queue holding thousands of paths
        # fills the OS pipe, and its feeder thread then blocks the app from exiting.
        self._backlog = deque()   # path_keys not yet handed to the process
        self._in_flight = []      # handed to the process, not finished yet
        self._missing = 0
        self._current = None      # (key, file name) being analysed by the process
        self._crashes = 0
        self.device = ''          # set when the model is loaded, e.g. 'GPU (CUDA)' or 'CPU'
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    @property
    def running(self):
        return self._process is not None and self._process.is_alive()

    def submit(self, tracks):
        """Queue (path_key, file_path) pairs. Resubmitting is cheap: known tracks are ignored."""
        for key, path in tracks:
            if key and key not in self._submitted:
                self._submitted[key] = path
                self._backlog.append(key)
        self._top_up()
        self._report()

    def start(self):
        if self.running:
            return
        self._jobs, self._events, self._stop = (self._context.Queue(), self._context.Queue(),
                                                self._context.Event())
        self._process = self._context.Process(
            target=run_analysis, name='embedding-analysis', daemon=True,
            args=(str(self.model_path), str(self.store.path), self._jobs, self._events, self._stop,
                  self.embedder_factory))
        self._process.start()
        self._top_up()
        self._timer.start(POLL_INTERVAL_MS)
        self._report('starting')

    def stop(self, timeout=3.0):
        """Stop the process; unfinished tracks are analysed after the next start()."""
        if self._process is None:
            return
        self._stop.set()
        self._process.join(timeout)
        if self._process.is_alive():
            self._process.terminate()  # safe: every result is its own SQLite transaction
            self._process.join(1)
        self._drain()
        self._end_process()
        self._report()

    def _end_process(self):
        self._timer.stop()
        for jobs in (self._jobs, self._events):
            jobs.cancel_join_thread()  # never wait for undelivered jobs when the app exits
            jobs.close()
        self._process = None
        self._current = None
        # Unfinished jobs go back to the front of the backlog for the next start().
        self._backlog.extendleft(reversed([key for key in self._in_flight if key not in self._finished]))
        self._in_flight = []

    def _top_up(self):
        if not self.running:
            return
        while len(self._in_flight) < IN_FLIGHT and self._backlog:
            key = self._backlog.popleft()
            if key not in self._finished:
                self._in_flight.append(key)
                self._jobs.put((key, self._submitted[key]))

    def wait_idle(self, timeout):
        """Process events until every submitted track is finished (tests, self-check)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._poll()
            if len(self._finished) >= len(self._submitted):
                return True
            if self._process is None:
                return False
            time.sleep(0.05)
        return False

    def _report(self, current=None):
        name = current if current is not None else (self._current[1] if self._current else '')
        self.progress.emit(len(self._finished), len(self._submitted), self._missing, name)

    def _drain(self):
        while True:
            try:
                event = self._events.get_nowait()
            except (queue.Empty, OSError, ValueError):
                return
            self._handle(event)

    def _handle(self, event):
        kind = event[0]
        if kind == 'ready':
            self.device = DEVICE_NAMES.get(event[1], event[1])
            self._report()
        elif kind == 'start':
            self._current = (event[1], event[2])
            self._report()
        elif kind == 'done':
            key, status = event[1], event[2]
            self._current = None
            if status == 'cancelled':
                return
            self._crashes = 0
            self._finished.add(key)
            if key in self._in_flight:
                self._in_flight.remove(key)
            self._missing += status == 'missing'
            if status == 'analysed':
                self.track_analyzed.emit(key)
            self._top_up()
            self._report()
        elif kind == 'fatal':
            self._give_up(f'Embedding analysis stopped: {event[1]}')

    def _poll(self):
        if self._process is None:
            return
        self._drain()
        if self._process is None or self._process.is_alive() or self._stop.is_set():
            return  # stopped by a 'fatal' event, still running, or stopping on request
        # The process died without being asked to.
        self._crashes += 1
        if self._current is not None:
            key = self._current[0]
            try:  # remember the file so it is not retried until it changes
                self.store.save_error(key, file_fingerprint(self._submitted[key]), 'analysis process crashed on this file')
            except (OSError, sqlite3.Error):
                pass
            self._finished.add(key)
        self._end_process()
        if self._crashes >= MAX_CRASHES:
            self._give_up('Embedding analysis stopped: the analysis process keeps crashing')
        else:
            self.start()

    def _give_up(self, message):
        self.stop(timeout=1)
        self.failed.emit(message)

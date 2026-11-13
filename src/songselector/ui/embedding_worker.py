"""Runs embedding analysis in background processes and reports progress to the UI.

Why processes and not threads (see core/embeddings.py): onnxruntime crashes when it loads after PyQt5 in the same
process, and a decoder crash on a broken file must not close the app. The processes write results to the model
caches themselves; this object only hands them jobs and turns their events into Qt signals.

Several processes can share the job queue. On a GPU one stream keeps it busy only part of the time (DirectML on a
GTX 1650 Ti: ~36 % load), and a second stream nearly doubled throughput at ~65 % load, leaving headroom for the rest
of the system. So `workers='auto'` starts one process, and a second once the first reports a GPU. The first process
also tunes the batch sizes (OnnxEmbedder.tune) before the others start, so its measurement is not disturbed.
"""
import multiprocessing
import queue
import sqlite3
import time
from collections import deque
from functools import partial
from pathlib import Path

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from songselector.core.embeddings import Cnn14Embedder, OnnxEmbedder, file_fingerprint, run_analysis

MAX_CRASHES = 3          # consecutive crashes before giving up (e.g. a broken model or runtime)
POLL_INTERVAL_MS = 200
IN_FLIGHT = 4            # jobs handed to each process ahead of time
GPU_STREAMS = 2          # processes for workers='auto' on a GPU
DEVICE_NAMES = {'CUDAExecutionProvider': 'GPU (CUDA)', 'DmlExecutionProvider': 'GPU (DirectML)',
                'CPUExecutionProvider': 'CPU'}


class EmbeddingAnalyzer(QObject):
    # done, total, missing files, file name being analysed ('' when idle)
    progress = pyqtSignal(int, int, int, str)
    track_analyzed = pyqtSignal(str)   # path_key
    failed = pyqtSignal(str)           # analysis stopped and will not continue by itself
    warning = pyqtSignal(str)          # e.g. one of several models could not be loaded

    def __init__(self, store, model_path, embedder_factory=Cnn14Embedder, parent=None, extra_models=()):
        """store / model_path: the first model (its EmbeddingStore knows which model it is).
        extra_models: [(store, model_path)] of further models, analysed in the same process from the same decode;
        (store, model_path, factory) to give a model its own embedder factory (tests).
        Set `workers` ('auto' or a number of processes) and `tuning_file` before start()."""
        super().__init__(parent)
        self.store = store
        self.model_path = Path(model_path)
        self.embedder_factory = embedder_factory  # must be picklable (a module-level class)
        self.extra_models = [(entry[0], Path(entry[1]),
                              entry[2] if len(entry) > 2 else partial(OnnxEmbedder, model_id=entry[0].spec.id))
                             for entry in extra_models]
        self.workers = 1          # 'auto': 2 on a GPU, 1 on the CPU; or a number
        self.tuning_file = None   # where tuned batch sizes are remembered; None: no tuning
        self._context = multiprocessing.get_context('spawn')
        self._processes = {}      # worker number -> process
        self._jobs = self._events = self._stop = None
        self._submitted = {}      # path_key -> file path, in submission order
        self._finished = set()
        # Jobs go to the processes a few at a time: a queue holding thousands of paths
        # fills the OS pipe, and its feeder thread then blocks the app from exiting.
        self._backlog = deque()   # path_keys not yet handed to a process
        self._in_flight = []      # handed to a process, not finished yet
        self._missing = 0
        self._current = {}        # worker number -> (key, file name) being analysed
        self._crashes = 0
        self.device = ''          # set when the models are loaded, e.g. 'GPU (DirectML)' or 'CPU'
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    @property
    def running(self):
        return any(process.is_alive() for process in self._processes.values())

    @property
    def configuration(self):
        """Which models with which files: a different one needs a new analyzer."""
        return tuple((store.spec.id, str(path)) for store, path, *_ in [(self.store, self.model_path)] + self.extra_models)

    def _models(self):
        first = (self.store.spec.id, str(self.model_path), str(self.store.path), self.embedder_factory)
        return [first] + [(store.spec.id, str(path), str(store.path), factory) for store, path, factory in self.extra_models]

    def _wanted_workers(self, provider):
        if self.workers == 'auto':
            return GPU_STREAMS if provider and provider != 'CPUExecutionProvider' else 1
        return max(1, int(self.workers))

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
        self._start_worker(0)  # the others follow its 'ready' (after it tuned the batch sizes)
        self._top_up()
        self._timer.start(POLL_INTERVAL_MS)
        self._report('starting')

    def _start_worker(self, number):
        process = self._context.Process(
            target=run_analysis, name=f'embedding-analysis-{number}', daemon=True,
            args=(self._models(), self._jobs, self._events, self._stop, number,
                  str(self.tuning_file) if self.tuning_file else None))
        process.start()
        self._processes[number] = process

    def stop(self, timeout=3.0):
        """Stop the processes; unfinished tracks are analysed after the next start()."""
        if not self._processes:
            return
        self._stop.set()
        deadline = time.monotonic() + timeout
        for process in self._processes.values():
            process.join(max(0.0, deadline - time.monotonic()))
            if process.is_alive():
                process.terminate()  # safe: every result is its own SQLite transaction
                process.join(1)
        self._drain()
        self._end_processes()
        self._report()

    def _end_processes(self):
        self._timer.stop()
        for channel in (self._jobs, self._events):
            channel.cancel_join_thread()  # never wait for undelivered jobs when the app exits
            channel.close()
        self._processes = {}
        self._current = {}
        self._requeue_unfinished()

    def _requeue_unfinished(self):
        """Unfinished jobs go back to the front of the backlog for the next start()."""
        self._backlog.extendleft(reversed([key for key in self._in_flight if key not in self._finished]))
        self._in_flight = []

    def _top_up(self):
        if not self.running:
            return
        while len(self._in_flight) < IN_FLIGHT * len(self._processes) and self._backlog:
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
            if not self._processes:
                return False
            time.sleep(0.05)
        return False

    def _report(self, current=None):
        if current is None:
            current = next(iter(self._current.values()), (None, ''))[1]
        self.progress.emit(len(self._finished), len(self._submitted), self._missing, current)

    def _drain(self):
        while self._events is not None:
            try:
                event = self._events.get_nowait()
            except (queue.Empty, OSError, ValueError):
                return
            self._handle(event)

    def _handle(self, event):
        kind, worker = event[0], event[-1]
        if kind == 'ready':
            self.device = DEVICE_NAMES.get(event[1], event[1])
            if worker == 0 and self._stop is not None and not self._stop.is_set():
                for number in range(1, self._wanted_workers(event[1])):
                    if number not in self._processes:
                        self._start_worker(number)
                self._top_up()
            self._report()
        elif kind == 'start':
            self._current[worker] = (event[1], event[2])
            self._report()
        elif kind == 'done':
            key, status = event[1], event[2]
            self._current.pop(worker, None)
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
        elif kind == 'warning':
            if worker == 0:  # every process would report the same
                self.warning.emit(event[1])
        elif kind == 'fatal':
            self._give_up(f'Embedding analysis stopped: {event[1]}')

    def _poll(self):
        if not self._processes:
            return
        self._drain()
        if not self._processes or self._stop.is_set():
            return  # stopped by a 'fatal' event, or stopping on request
        for number, process in list(self._processes.items()):
            if process.is_alive():
                continue
            # This process died without being asked to.
            self._crashes += 1
            current = self._current.pop(number, None)
            if current is not None:
                key = current[0]
                for store in [self.store] + [extra[0] for extra in self.extra_models]:
                    try:  # remember the file so it is not retried until it changes
                        store.save_error(key, file_fingerprint(self._submitted[key]),
                                         'analysis process crashed on this file')
                    except (OSError, sqlite3.Error):
                        pass
                self._finished.add(key)
                if key in self._in_flight:
                    self._in_flight.remove(key)
            del self._processes[number]
            if self._crashes >= MAX_CRASHES:
                self._give_up('Embedding analysis stopped: the analysis process keeps crashing')
                return
            if not self._processes:
                # The only process died: jobs it held are lost with its queue reader; start over cleanly.
                self._end_processes()
                self.start()
                return
            self._start_worker(number)
        self._top_up()

    def _give_up(self, message):
        self.stop(timeout=1)
        self.failed.emit(message)

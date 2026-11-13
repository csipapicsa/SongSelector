"""Watches Traktor's collection.nml (or Rekordbox's master.db) and re-reads it in the background
after the program saves.

Traktor rewrites the whole file (often by replacing it), mostly when it closes, so the
folder is watched as well as the file, and a slow poll catches what the watcher misses
(e.g. network drives). After a change the file must stay unchanged for SETTLE_MS before it
is read: a half-written NML would not parse. Reading runs in a low-priority thread; the
result arrives in the GUI thread as one TraktorCollection (the window applies it in one batch).
Rekordbox's library works the same way: pass `reader=RekordboxLibrary` and its `signature`.
"""
import os
import sys
import threading
from pathlib import Path

from PyQt5.QtCore import QFileSystemWatcher, QObject, QTimer, pyqtSignal

from songselector.core.traktor_collection import TraktorCollection

SETTLE_MS = 3000         # the file must be unchanged this long before it is read
POLL_MS = 60000          # fallback check of size and modification time
FIRST_CHECK_MS = 5000    # after start: changes made in Traktor while the app was closed


def file_signature(path):
    try:
        stat = os.stat(path)
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


def _lower_thread_priority():
    if sys.platform == 'win32':
        try:
            import ctypes
            kernel = ctypes.windll.kernel32
            kernel.SetThreadPriority(kernel.GetCurrentThread(), -2)  # THREAD_PRIORITY_LOWEST
        except (AttributeError, OSError):
            pass


class CollectionWatcher(QObject):
    loaded = pyqtSignal(object)   # TraktorCollection (or the reader's object), read after a change
    failed = pyqtSignal(str)      # the file changed but could not be read: the message
    _done = pyqtSignal(object)    # from the reading thread

    def __init__(self, path='', parent=None, first_check_ms=FIRST_CHECK_MS, reader=TraktorCollection,
                 signature=file_signature):
        super().__init__(parent)
        self._reader, self._signature = reader, signature
        self.path = ''
        self._read_signature = None   # signature of the file the last result came from
        self._pending = None          # signature seen at the last change, waiting to settle
        self._busy = False
        self._stopped = False
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._changed)
        self._watcher.directoryChanged.connect(self._changed)
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.timeout.connect(self._settled)
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._changed)
        self._done.connect(self._finished)
        self.set_path(path, first_check_ms)

    def set_path(self, path, first_check_ms=FIRST_CHECK_MS):
        """Watch another collection file ('' stops watching)."""
        for watched in self._watcher.files() + self._watcher.directories():
            self._watcher.removePath(watched)
        self.path = str(path or '')
        self._read_signature = self._pending = None
        self._poll.stop()
        if not self.path or self._stopped:
            return
        folder = str(Path(self.path).parent)
        if os.path.isdir(folder):
            self._watcher.addPath(folder)
        if os.path.isfile(self.path):
            self._watcher.addPath(self.path)
        self._poll.start(POLL_MS)
        self._settle.start(first_check_ms)

    def stop(self):
        self._stopped = True
        self._settle.stop()
        self._poll.stop()

    def _changed(self, _path=''):
        if self._stopped or not self.path:
            return
        if self.path not in self._watcher.files() and os.path.isfile(self.path):
            self._watcher.addPath(self.path)  # Traktor replaced the file: watch the new one
        signature = self._signature(self.path)
        if signature is None or signature == self._read_signature:
            return
        self._pending = signature
        self._settle.start(SETTLE_MS)  # restarts while Traktor keeps writing

    def _settled(self):
        signature = self._signature(self.path)
        if self._stopped or signature is None:
            return
        if signature != self._pending and self._pending is not None:
            self._pending = signature  # still being written
            self._settle.start(SETTLE_MS)
            return
        if signature == self._read_signature:
            return
        if self._busy:
            self._settle.start(SETTLE_MS)  # read again when the current read is done
            return
        self._busy = True
        path = self.path

        def work():
            _lower_thread_priority()
            collection = self._reader(path)
            collection._load()
            self._done.emit((path, signature, collection))

        threading.Thread(target=work, name='traktor-collection-sync', daemon=True).start()

    def _finished(self, result):
        path, signature, collection = result
        self._busy = False
        if self._stopped or path != self.path:
            return
        self._read_signature = signature  # an unreadable version is not retried; the next save is
        if collection.error:
            self.failed.emit(collection.error)
        else:
            self.loaded.emit(collection)

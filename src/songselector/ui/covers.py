"""Cover thumbnails for the List, the Playlist and the map: loaded in the background, cached on disk.

`CoverProvider.pixmap(path)` answers at once from memory; if the cover is not there yet it is requested and the
`ready` signal tells when it arrived (the views then repaint). A worker thread reads the file (core.cover_art),
scales the picture to a thumbnail with QImage (safe outside the UI thread, unlike QPixmap) and stores it in the
cache folder, with an empty marker for tracks without a cover, so neither is read again until the file or its
folder changes. Only rows that are painted ask, so a library of thousands of tracks loads only what is seen.
"""
import queue
import threading
from collections import OrderedDict
from pathlib import Path

from PyQt5.QtCore import QObject, QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from songselector.config import HEADER_INDEX
from songselector.core.cover_art import cache_keys, find_cover
from songselector.core.traktor_collection import canonical_path

THUMBNAIL = 128          # px, longest side of a cached thumbnail (enough for the largest column size)
MEMORY_LIMIT = 3000      # thumbnails kept in memory (about 50 KB each)
OFF, CROPPED, SQUARE = 'off', 'cropped', 'square'
STYLES = {OFF: 'Off', CROPPED: 'Cropped to the row height (top of the picture)', SQUARE: 'Square rows (whole picture)'}
SIZES = (48, 72, 96)


class CoverProvider(QObject):
    ready = pyqtSignal(str)   # path_key whose cover (or "no cover") is now known
    _loaded = pyqtSignal(str, object)  # worker -> UI thread: path_key, QImage or None

    def __init__(self, cache_dir, parent=None, finder=find_cover):
        super().__init__(parent)
        self.cache_dir = Path(cache_dir)
        self.finder = finder
        self._memory = OrderedDict()   # path_key -> QPixmap, or None (no cover)
        self._pending = set()
        self._jobs = queue.LifoQueue()  # the most recently painted rows first
        self._loaded.connect(self._store)
        self._thread = threading.Thread(target=self._run, name='cover-art', daemon=True)
        self._thread.start()

    def pixmap(self, path):
        """The cover thumbnail if it is known (None: no cover, or not loaded yet; then it is requested)."""
        key = canonical_path(path)
        if not key:
            return None
        if key in self._memory:
            self._memory.move_to_end(key)
            return self._memory[key]
        if key not in self._pending:
            self._pending.add(key)
            self._jobs.put((key, str(path)))
        return None

    def known(self, path):
        return canonical_path(path) in self._memory

    def cached_file(self, path):
        """Path of the thumbnail on disk (for HTML, e.g. the map's cards), or None."""
        name, _none = cache_keys(path)
        if name is None:
            return None
        file = self.cache_dir / f'{name}.png'
        return file if file.is_file() else None

    def stop(self, timeout=1.0):
        """End the loader after the file it is reading (so that file is closed when this returns, if in time)."""
        self._jobs.put(None)
        self._thread.join(timeout)

    def _run(self):
        while True:
            job = self._jobs.get()
            if job is None:
                return
            key, path = job
            try:
                image = self._load(path)
            except Exception:  # a broken file must not stop the loader: no cover
                image = None
            self._loaded.emit(key, image)

    def _load(self, path):
        name, none_name = cache_keys(path)
        if name is None:
            return None
        thumbnail, marker = self.cache_dir / f'{name}.png', self.cache_dir / f'{none_name}.none'
        if thumbnail.is_file():
            image = QImage(str(thumbnail))
            return None if image.isNull() else image
        if marker.is_file():
            return None
        data = self.finder(path)
        image = QImage.fromData(data) if data else QImage()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if image.isNull():
            marker.touch()
            return None
        image = image.scaled(THUMBNAIL, THUMBNAIL, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        image.save(str(thumbnail), 'PNG')
        return image

    def _store(self, key, image):
        self._pending.discard(key)
        self._memory[key] = QPixmap.fromImage(image) if image is not None else None
        while len(self._memory) > MEMORY_LIMIT:
            self._memory.popitem(last=False)
        self.ready.emit(key)


class CoverDelegate(QStyledItemDelegate):
    """Paints the Cover column: the thumbnail cropped to the row height (top of the picture), or in square rows."""

    def __init__(self, provider, settings, parent=None):
        super().__init__(parent)
        self.provider, self.settings = provider, settings

    def style(self):
        return self.settings.get('Cover art', OFF)

    def size(self):
        return int(self.settings.get('Cover size', SIZES[0]))

    def sizeHint(self, option, index):
        size = self.size()
        if self.style() == SQUARE:
            return QSize(size, size)
        return QSize(size, super().sizeHint(option, index).height())

    def paint(self, painter, option, index):
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        styled.text = ''
        style = styled.widget.style() if styled.widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, styled, painter, styled.widget)
        if self.style() == OFF:
            return
        path = index.sibling(index.row(), HEADER_INDEX['Path']).data()
        pixmap = self.provider.pixmap(path) if path else None
        if pixmap is None or pixmap.isNull():
            return
        rect = option.rect
        painter.save()
        painter.setClipRect(rect)
        if self.style() == SQUARE:
            scaled = pixmap.scaled(rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            target = QRect(rect.x() + (rect.width() - scaled.width()) // 2,
                           rect.y() + (rect.height() - scaled.height()) // 2, scaled.width(), scaled.height())
        else:  # the picture as wide as the column, its top part in the row
            scaled = pixmap.scaledToWidth(rect.width(), Qt.SmoothTransformation)
            target = QRect(rect.x(), rect.y(), scaled.width(), scaled.height())
        painter.drawPixmap(target, scaled)
        painter.restore()

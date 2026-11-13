"""Analysis -> Download models: fetch the model files into the models folder (core/model_download.py)."""
import threading
import time

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from songselector.core import model_download
from songselector.core.model_download import BASE_URL, FILES, LICENCES, RELEASE_PAGE


class _Events(QObject):
    progress = pyqtSignal(str, float, float)   # file name, bytes done, bytes in all
    finished = pyqtSignal(list, str)           # ids of complete models, error text ('' if none)


class ModelDownloadDialog(QDialog):
    downloaded = pyqtSignal(list)   # ids of models that became complete

    def __init__(self, models, folder, base_url=BASE_URL, files=FILES, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Download models')
        self.setAttribute(Qt.WA_QuitOnClose, False)  # never keeps the app running after the main window closes
        self.models, self.folder, self.base_url, self.files = models, folder, base_url, files
        self._stop = threading.Event()
        self._thread = None
        self._started = 0.0
        self._events = _Events()
        self._events.progress.connect(self._progress)
        self._events.finished.connect(self._finished)

        layout = QVBoxLayout(self)
        intro = QLabel(
            'The models turn your tracks into embeddings (similarity map, closest matches, groups); the CLAP '
            'models also enable <b>Search by description</b>. They are downloaded once into<br>'
            f'<code>{folder}</code><br>from the project\'s '
            f'<a href="{RELEASE_PAGE}">model release</a> (sources and licences are listed there) '
            'and checked before use.')
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        intro.setOpenExternalLinks(True)
        layout.addWidget(intro)
        self.boxes = {}
        for spec in models:
            installed = model_download.installed(spec, folder, files)
            size = model_download.download_size(spec, files) / 1e6
            box = QCheckBox(f'{spec.name}: {size:,.0f} MB, {LICENCES.get(spec.id, "")}'
                            + (' (installed)' if installed else ''))
            box.setToolTip(spec.description)
            box.setChecked(not installed)
            box.setEnabled(not installed)
            self.boxes[spec.id] = box
            layout.addWidget(box)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.download_button = QPushButton('Download')
        self.download_button.setDefault(True)
        self.download_button.clicked.connect(self.start)
        self.stop_button = QPushButton('Stop')
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop.set)
        close = QPushButton('Close')
        close.clicked.connect(self.close)
        buttons.addStretch(1)
        buttons.addWidget(self.download_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._update_button()
        for box in self.boxes.values():
            box.toggled.connect(self._update_button)
        self.resize(560, self.sizeHint().height())

    def chosen(self):
        return [spec for spec in self.models if self.boxes[spec.id].isEnabled() and self.boxes[spec.id].isChecked()]

    def _update_button(self):
        chosen = self.chosen()
        total = sum(model_download.download_size(spec, self.files) for spec in chosen) / 1e6
        self.download_button.setEnabled(bool(chosen) and self._thread is None)
        self.download_button.setText(f'Download ({total:,.0f} MB)' if chosen else 'Download')

    @property
    def running(self):
        return self._thread is not None

    def start(self):
        chosen = self.chosen()
        if not chosen or self._thread is not None:
            return
        self._stop.clear()
        self._started = time.monotonic()
        self.download_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        for box in self.boxes.values():
            box.setEnabled(False)
        self.status.setText('Connecting...')

        def work():
            error = ''
            try:
                model_download.download_models(chosen, self.folder, self.base_url, self.files,
                                               lambda name, done, total: self._events.progress.emit(name, done, total),
                                               self._stop.is_set)
            except model_download.Cancelled:
                error = 'Stopped. Download again to continue where it stopped.'
            except Exception as problem:  # network, disk, checksum
                error = f'{type(problem).__name__}: {problem}'
            complete = [spec.id for spec in self.models if model_download.installed(spec, self.folder, self.files)]
            self._events.finished.emit(complete, error)
        self._thread = threading.Thread(target=work, name='model-download', daemon=True)
        self._thread.start()

    def _progress(self, name, done, total):
        self.bar.setValue(int(1000 * done / total) if total else 1000)
        elapsed = max(time.monotonic() - self._started, 1e-3)
        self.status.setText(f'{name}: {done / 1e6:,.0f} of {total / 1e6:,.0f} MB ({done / 1e6 / elapsed:.1f} MB/s)')

    def _finished(self, complete, error):
        self._thread = None
        self.stop_button.setEnabled(False)
        for spec in self.models:
            installed = spec.id in complete
            box = self.boxes[spec.id]
            box.setEnabled(not installed)
            box.setChecked(not installed and box.isChecked())
            if installed and '(installed)' not in box.text():
                box.setText(box.text() + ' (installed)')
        self._update_button()
        if error:
            self.status.setText(error)
        else:
            self.bar.setValue(1000)
            self.status.setText('Done. The models are switched on and your tracks are being analysed in the background.')
        self.downloaded.emit(complete)

    def wait(self, timeout):
        """Wait for a running download (tests)."""
        if self._thread is not None:
            self._thread.join(timeout)

    def closeEvent(self, event):
        self._stop.set()  # a running download stops after its current block; the .part file stays for next time
        super().closeEvent(event)

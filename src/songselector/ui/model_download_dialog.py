"""Analysis -> Get models: which model files are installed; downloads the missing ones (core/model_download.py),
from Hugging Face or from the `Model download URL` set in the settings."""
import threading
import time
from pathlib import Path

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
from songselector.core.model_download import BUILD_HELP, FILES, LICENCES


class _Events(QObject):
    progress = pyqtSignal(str, float, float)   # file name, bytes done, bytes in all
    finished = pyqtSignal(list, str)           # ids of complete models, error text ('' if none)


class ModelDownloadDialog(QDialog):
    downloaded = pyqtSignal(list)   # ids of models that became complete
    folder_chosen = pyqtSignal(str)  # the user picked another models folder (Models folder...)

    def __init__(self, models, folder, base_url='', files=FILES, parent=None):
        """base_url: a web folder serving the files under their names; empty for the Hugging Face repos."""
        super().__init__(parent)
        self.setWindowTitle('Get models')
        self.setAttribute(Qt.WA_QuitOnClose, False)  # never keeps the app running after the main window closes
        self.models, self.folder, self.base_url, self.files = models, Path(folder), base_url, files
        self._stop = threading.Event()
        self._thread = None
        self._started = 0.0
        self._events = _Events()
        self._events.progress.connect(self._progress)
        self._events.finished.connect(self._finished)

        layout = QVBoxLayout(self)
        self.intro = QLabel(self._intro_text())
        self.intro.setWordWrap(True)
        self.intro.setTextFormat(Qt.RichText)
        self.intro.setOpenExternalLinks(True)
        layout.addWidget(self.intro)
        self.boxes = {}
        for spec in models:
            box = QCheckBox()
            box.setToolTip(spec.description)
            self.boxes[spec.id] = box
            layout.addWidget(box)
        self._show_installed()
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
        # One button that chooses (asked 2026-11-20: "Open models folder" only opened it, which has no purpose). The
        # picker starts in the current folder, so it also shows what is there.
        self.folder_button = QPushButton('Models folder...')
        self.folder_button.setToolTip('Choose the folder the app reads the model files from and downloads them into,\n'
                                      'e.g. one that already holds them or is shared by several installations.')
        self.folder_button.clicked.connect(self._choose_folder)
        buttons.addWidget(self.folder_button)
        buttons.addStretch(1)
        buttons.addWidget(self.download_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._update_button()
        for box in self.boxes.values():
            box.toggled.connect(self._update_button)
        self.resize(560, self.sizeHint().height())

    def _intro_text(self):
        purpose = ('The models turn your tracks into embeddings (similarity map, closest matches, groups); the CLAP '
                   'models also enable <b>Search by description</b>. ')
        source = f'<code>{self.base_url}</code>' if self.base_url else 'Hugging Face'
        return (purpose + f'They are downloaded once from {source} into<br><code>{self.folder}</code><br>and '
                f'checked before use. You can also build them yourself (<a href="{BUILD_HELP}">how</a>).')

    def _show_installed(self):
        """Each model's box: installed ones done (greyed out), missing ones checked for download."""
        for spec in self.models:
            installed = model_download.installed(spec, self.folder, self.files)
            size = model_download.download_size(spec, self.files) / 1e6
            box = self.boxes[spec.id]
            box.setText(f'{spec.name}: {size:,.0f} MB, {LICENCES.get(spec.id, "")}' + (' (installed)' if installed else ''))
            box.setChecked(not installed)
            box.setEnabled(not installed)

    def _choose_folder(self):
        from PyQt5.QtWidgets import QFileDialog
        chosen = QFileDialog.getExistingDirectory(self, 'Models folder', str(self.folder))
        if chosen and Path(chosen) != self.folder:
            self.set_folder(chosen)
            self.folder_chosen.emit(str(self.folder))

    def set_folder(self, folder):
        """Show another models folder: what is installed there and where downloads go."""
        if self._thread is not None:
            return  # never while a download writes into the old one (the button is disabled then)
        self.folder = Path(folder)
        self.intro.setText(self._intro_text())
        self._show_installed()
        self._update_button()

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
        self.folder_button.setEnabled(False)  # the download writes into this folder
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
        self.folder_button.setEnabled(True)
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

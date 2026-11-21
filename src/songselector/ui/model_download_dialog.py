"""Analysis -> Get models: the state of each model's files (installed, being checked, missing, damaged), and the
download of what is missing or damaged (core/model_download.py), from Hugging Face or from the `Model download URL`
set in the settings."""
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
from songselector.core.model_download import (
    BUILD_HELP,
    CHECKING,
    DAMAGED,
    FILES,
    INCOMPLETE,
    INSTALLED,
    LICENCES,
    NOT_INSTALLED,
)

# What each model's row says on the right, and in which colour.
STATE_TEXT = {INSTALLED: ('Installed', '#3cb44b'), CHECKING: ('Installed, checking the files...', '#8c9096'),
              NOT_INSTALLED: ('Not installed', ''), INCOMPLETE: ('Incomplete', '#f0a030'),
              DAMAGED: ('Damaged: downloaded again', '#e6194b')}


class _Events(QObject):
    progress = pyqtSignal(str, float, float)   # file name, bytes done, bytes in all
    finished = pyqtSignal(list, str)           # ids of complete models, error text ('' if none)
    checked = pyqtSignal(str, list)            # a downloaded file's path and its check record


class ModelDownloadDialog(QDialog):
    downloaded = pyqtSignal(list)   # ids of models that became complete
    folder_chosen = pyqtSignal(str)  # the user picked another models folder (Models folder...)
    file_checked = pyqtSignal(str, list)  # a downloaded file passed its checksum: (path, record for `checked`)

    def __init__(self, models, folder, base_url='', files=FILES, checked=None, parent=None):
        """base_url: a web folder serving the files under their names; empty for the Hugging Face repos.
        checked: the app's checksum records ({path: [size, mtime_ns, ok]}, model_download.file_state); read only
        here, the main window keeps them up to date and calls refresh()."""
        super().__init__(parent)
        self.checked = checked if checked is not None else {}
        self.setWindowTitle('Get models')
        self.setAttribute(Qt.WA_QuitOnClose, False)  # never keeps the app running after the main window closes
        self.models, self.folder, self.base_url, self.files = models, Path(folder), base_url, files
        self._stop = threading.Event()
        self._thread = None
        self._started = 0.0
        self._events = _Events()
        self._events.progress.connect(self._progress)
        self._events.finished.connect(self._finished)
        self._events.checked.connect(self._file_checked)

        layout = QVBoxLayout(self)
        self.intro = QLabel(self._intro_text())
        self.intro.setWordWrap(True)
        self.intro.setTextFormat(Qt.RichText)
        self.intro.setOpenExternalLinks(True)
        layout.addWidget(self.intro)
        # One row per model: a check box to download it while it is missing or damaged; an installed one shows a
        # check mark instead (a greyed-out, empty check box read as "not there", user 2026-11-20 and 2026-11-21).
        self.boxes, self.done_labels, self.state_labels = {}, {}, {}
        for spec in models:
            row = QHBoxLayout()
            box, done, state = QCheckBox(), QLabel(), QLabel()
            for widget in (box, done):
                widget.setToolTip(spec.description)
            self.boxes[spec.id], self.done_labels[spec.id], self.state_labels[spec.id] = box, done, state
            row.addWidget(box)
            row.addWidget(done)
            row.addStretch(1)
            row.addWidget(state)
            layout.addLayout(row)
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
        self._fit_height()

    def _intro_text(self):
        purpose = ('The models turn your tracks into embeddings (similarity map, closest matches, groups); the CLAP '
                   'models also enable <b>Search by description</b>. ')
        source = f'<code>{self.base_url}</code>' if self.base_url else 'Hugging Face'
        return (purpose + f'They are downloaded once from {source} into<br><code>{self.folder}</code><br>and '
                f'checked before use. You can also build them yourself (<a href="{BUILD_HELP}">how</a>).')

    def _fit_height(self):
        """Tall enough for the intro wrapped at the window's width, also after another folder changed its text (it
        was cut off once: "...You can also build them yourself (how)." missing, seen on Linux)."""
        width = max(self.width(), 560) if self.isVisible() else 560
        self.resize(width, max(self.sizeHint().height(), self.layout().heightForWidth(width)))

    def _show_installed(self, keep_choice=False):
        """Each model's row: installed ones with a check mark, missing or damaged ones checked for download (with
        keep_choice, those keep the user's tick)."""
        for spec in self.models:
            states = model_download.file_states(spec, self.folder, self.files, self.checked)
            state = model_download.model_state(states)
            size = model_download.download_size(spec, self.files) / 1e6
            title = f'{spec.name}: {size:,.0f} MB, {LICENCES.get(spec.id, "")}'
            there = state in (INSTALLED, CHECKING)
            box, done, label = self.boxes[spec.id], self.done_labels[spec.id], self.state_labels[spec.id]
            was_offered = not box.isHidden()
            box.setText(title)
            done.setText(f'<span style="color:#3cb44b">&#10004;</span> {title}')
            box.setHidden(there)
            done.setHidden(not there)
            if not there and not (keep_choice and was_offered):
                box.setChecked(True)
            box.setEnabled(self._thread is None)
            text, colour = STATE_TEXT[state]
            label.setText(f'<span style="color:{colour}">{text}</span>' if colour else text)
            problems = model_download.problems(states)
            label.setToolTip(f'{problems}.' if problems else
                             'All files are there, with the right size and SHA-256.' if state == INSTALLED else
                             'All files are there with the right size; their SHA-256 is being checked.' if there else '')

    def refresh(self):
        """The main window checked files: show the new states (the ticks of missing models stay as they are)."""
        if self._thread is None:
            self._show_installed(keep_choice=True)
            self._update_button()

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
        self._fit_height()

    def chosen(self):
        return [spec for spec in self.models if not self.boxes[spec.id].isHidden()
                and self.boxes[spec.id].isEnabled() and self.boxes[spec.id].isChecked()]

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

        checked = dict(self.checked)  # the worker's own copy: the main window changes the original

        def work():
            error = ''
            try:
                model_download.download_models(chosen, self.folder, self.base_url, self.files,
                                               lambda name, done, total: self._events.progress.emit(name, done, total),
                                               self._stop.is_set, checked,
                                               lambda path, record: self._events.checked.emit(path, record))
            except model_download.Cancelled:
                error = 'Stopped. Download again to continue where it stopped.'
            except Exception as problem:  # network, disk, checksum
                error = f'{type(problem).__name__}: {problem}'
            complete = [spec.id for spec in self.models
                        if model_download.installed(spec, self.folder, self.files, checked)]
            self._events.finished.emit(complete, error)
        self._thread = threading.Thread(target=work, name='model-download', daemon=True)
        self._thread.start()

    def _progress(self, name, done, total):
        self.bar.setValue(int(1000 * done / total) if total else 1000)
        elapsed = max(time.monotonic() - self._started, 1e-3)
        self.status.setText(f'{name}: {done / 1e6:,.0f} of {total / 1e6:,.0f} MB ({done / 1e6 / elapsed:.1f} MB/s)')

    def _file_checked(self, path, record):
        self.checked[path] = record  # also reported to the main window, which keeps the records
        self.file_checked.emit(path, record)

    def _finished(self, complete, error):
        self._thread = None
        self.stop_button.setEnabled(False)
        self.folder_button.setEnabled(True)
        self._show_installed(keep_choice=True)
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

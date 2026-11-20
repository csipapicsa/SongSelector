"""Downloading the model files: resume, checksums, cancelling, the download window. Against a local HTTP server."""
import hashlib
import os
import re
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from songselector.core import model_download
from songselector.core.embedding_models import CNN14, LAION_CLAP
from songselector.core.model_download import FILES, Cancelled, DownloadError, download, download_models, installed


class Handler(BaseHTTPRequestHandler):
    """Serves `files`; answers Range requests with 206 unless `ignore_range`."""
    files, ranges, ignore_range = {}, [], False

    def do_GET(self):
        data = self.files.get(self.path.lstrip('/'))
        if data is None:
            self.send_error(404)
            return
        requested = self.headers.get('Range')
        self.ranges.append(requested)
        if requested and not self.ignore_range:
            start = int(requested.split('=')[1].rstrip('-'))
            body = data[start:]
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{len(data) - 1}/{len(data)}')
        else:
            body = data
            self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def manifest(files):
    return {name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in files.items()}


class ServerCase(unittest.TestCase):
    """A local HTTP server with one multi-block file."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.folder = Path(self.temp.name) / 'models'
        self.data = os.urandom(3 * model_download.BLOCK + 123)  # several blocks
        Handler.files = {'model.onnx': self.data}
        Handler.ranges, Handler.ignore_range = [], False
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/'
        self.files = manifest(Handler.files)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()


class DownloadTests(ServerCase):
    def test_download_checks_the_checksum_and_names_the_file_only_then(self):
        steps = []
        path = download('model.onnx', self.folder, self.url, self.files, lambda done, total: steps.append(done))
        self.assertEqual(path.read_bytes(), self.data)
        self.assertFalse((self.folder / 'model.onnx.part').exists())
        self.assertEqual(steps[-1], len(self.data))
        self.assertEqual(steps, sorted(steps))

    def test_resumes_where_a_previous_download_stopped(self):
        self.folder.mkdir()
        (self.folder / 'model.onnx.part').write_bytes(self.data[:1000])
        download('model.onnx', self.folder, self.url, self.files)
        self.assertEqual(Handler.ranges, ['bytes=1000-'])
        self.assertEqual((self.folder / 'model.onnx').read_bytes(), self.data)

    def test_starts_over_when_the_server_ignores_the_range(self):
        self.folder.mkdir()
        (self.folder / 'model.onnx.part').write_bytes(self.data[:1000])
        Handler.ignore_range = True
        download('model.onnx', self.folder, self.url, self.files)
        self.assertEqual((self.folder / 'model.onnx').read_bytes(), self.data)

    def test_a_wrong_checksum_never_becomes_a_model_file(self):
        files = {'model.onnx': (len(self.data), '0' * 64)}
        with self.assertRaises(DownloadError):
            download('model.onnx', self.folder, self.url, files)
        self.assertFalse((self.folder / 'model.onnx').exists())
        self.assertFalse((self.folder / 'model.onnx.part').exists())  # not resumed from bad data either

    def test_stop_keeps_the_part_file_for_next_time(self):
        with self.assertRaises(Cancelled):
            download('model.onnx', self.folder, self.url, self.files, should_stop=lambda: True)
        self.assertFalse((self.folder / 'model.onnx').exists())

    def test_downloads_every_missing_file_of_the_chosen_models(self):
        contents = {name: os.urandom(2000 + index) for index, name in enumerate(LAION_CLAP.files())}
        Handler.files = contents
        files = manifest(contents)
        self.folder.mkdir()
        first = LAION_CLAP.files()[0]
        (self.folder / first).write_bytes(contents[first])  # already there: not downloaded again
        totals = []
        complete = download_models([LAION_CLAP], self.folder, self.url, files,
                                   lambda name, done, total: totals.append((name, done, total)))
        self.assertEqual(complete, [LAION_CLAP])
        self.assertTrue(installed(LAION_CLAP, self.folder, files))
        self.assertNotIn(first, {name for name, _done, _total in totals})
        self.assertEqual(totals[-1][1], totals[-1][2])  # ends at 100 %

    def test_the_release_files_cover_every_model(self):
        from songselector.core.embedding_models import MODELS
        for spec in MODELS.values():
            for name in spec.files():
                self.assertIn(name, FILES)
        self.assertGreater(model_download.download_size(CNN14), 300e6)

    def test_every_file_comes_from_its_models_hugging_face_repo_at_a_pinned_commit(self):
        # A branch name like `main` would let a later push change what this app version downloads.
        self.assertEqual(set(model_download.URLS), set(FILES))
        pinned = re.compile(r'https://huggingface\.co/csipapicsa/songselector-[a-z0-9-]+/resolve/[0-9a-f]{40}/')
        for name, address in model_download.URLS.items():
            self.assertRegex(address, pinned)
            self.assertTrue(address.endswith('/' + name))
        self.assertIn('songselector-clap-ms/', model_download.url('clap-ms-text.onnx'))

    def test_a_download_url_in_the_settings_replaces_hugging_face(self):
        self.assertEqual(model_download.url('cnn14.onnx', 'https://example.org/models/'),
                         'https://example.org/models/cnn14.onnx')


class DownloadWindowTests(ServerCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_by_default_the_window_offers_the_download_from_hugging_face(self):
        # 2026-11-17 to 2026-11-20 there was no download source and the window only explained how to build them.
        from songselector.core.model_download import BUILD_HELP
        from songselector.ui.model_download_dialog import ModelDownloadDialog
        dialog = ModelDownloadDialog([LAION_CLAP], self.folder)
        try:
            self.assertEqual(dialog.windowTitle(), 'Get models')
            self.assertFalse(dialog.download_button.isHidden())
            self.assertTrue(dialog.download_button.isEnabled())
            self.assertTrue(dialog.boxes[LAION_CLAP.id].isChecked())  # missing: checked by default
            intro = dialog.findChildren(type(dialog.status))[0].text()
            self.assertIn('Hugging Face', intro)
            self.assertIn(BUILD_HELP, intro)  # building them yourself stays possible
        finally:
            dialog.close()

    def test_models_folder_button_chooses_the_folder_and_shows_what_is_there(self):
        # Asked 2026-11-20: "Open models folder" only opened the folder, which has no purpose; now one button
        # chooses it (the picker starts in the current folder, so it shows what is there).
        from unittest.mock import patch

        from songselector.ui.model_download_dialog import ModelDownloadDialog
        contents = {name: os.urandom(1500) for name in LAION_CLAP.files()}
        shared = Path(self.temp.name) / 'shared models'
        shared.mkdir()
        for name, data in contents.items():
            (shared / name).write_bytes(data)
        dialog = ModelDownloadDialog([LAION_CLAP], self.folder, self.url, manifest(contents))
        chosen = []
        dialog.folder_chosen.connect(chosen.append)
        try:
            self.assertEqual(dialog.folder_button.text(), 'Models folder...')
            self.assertNotIn('installed', dialog.boxes[LAION_CLAP.id].text())
            with patch('PyQt5.QtWidgets.QFileDialog.getExistingDirectory', return_value=str(shared)) as picker:
                dialog.folder_button.click()
            self.assertEqual(picker.call_args[0][2], str(self.folder))  # starts in the current folder
            self.assertEqual(chosen, [str(shared)])
            self.assertIn('(installed)', dialog.boxes[LAION_CLAP.id].text())
            self.assertFalse(dialog.boxes[LAION_CLAP.id].isEnabled())
            self.assertIn(str(shared), dialog.intro.text())  # downloads would go there
        finally:
            dialog.close()

    def test_window_downloads_the_checked_models_and_reports_them(self):
        from songselector.ui.model_download_dialog import ModelDownloadDialog
        contents = {name: os.urandom(1500) for name in LAION_CLAP.files()}
        Handler.files = contents
        dialog = ModelDownloadDialog([LAION_CLAP], self.folder, self.url, manifest(contents))
        reported = []
        dialog.downloaded.connect(reported.extend)
        try:
            self.assertTrue(dialog.boxes[LAION_CLAP.id].isChecked())  # missing: checked by default
            dialog.start()
            deadline = time.monotonic() + 20
            while not reported and time.monotonic() < deadline:
                self.application.processEvents()
                time.sleep(0.01)
            self.assertEqual(reported, [LAION_CLAP.id])
            self.assertIn('installed', dialog.boxes[LAION_CLAP.id].text())
            self.assertFalse(dialog.boxes[LAION_CLAP.id].isEnabled())
        finally:
            dialog.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)

"""Downloads the model files from the project's GitHub release `models-v1` into the models folder.

The files are the ONNX exports made by scripts/export_cnn14_onnx.py and scripts/export_clap_onnx.py (see MODELS.md
in the release for sources and licences). Each download goes to `<name>.part` first, resumes where it stopped
(HTTP Range), and gets its real name only after its SHA-256 matches the one below, so a broken or tampered file is
never used.

No PyQt5 here; ui/model_download_dialog.py runs this in a thread.
"""
import hashlib
import os
import urllib.request
from pathlib import Path

BASE_URL = 'https://github.com/csipapicsa/SongSelector/releases/download/models-v1/'
RELEASE_PAGE = 'https://github.com/csipapicsa/SongSelector/releases/tag/models-v1'

# name: (size in bytes, SHA-256); the same values as SHA256SUMS.txt in the release.
FILES = {
    'cnn14.onnx': (327330336, 'ae868eda6e9734f4722d61fe70e45ce215c316e3fe306023105ff3c0a9e73a32'),
    'clap-laion-audio.onnx': (121612865, '3c736ebc3a05f8cc652b93f2306e4c12eb714aba9e455f2c17541ed63042d55c'),
    'clap-laion-text.onnx': (501449463, '2cebcbe969166aa29db1750c688103cefc474b9ae478d747a3b4faa346ec5bbd'),
    'clap-laion-tokenizer.json': (3558802, '4fd1d86b4f5b53f40a609fcd11c1f34024b735f870a07439d70202b98493661a'),
    'clap-ms-audio.onnx': (126555913, 'e9b5c1cc2e43cd870a3df94535774bd4aed5456f0a7cc8c519a82e80c84b7ff2'),
    'clap-ms-text.onnx': (505456227, '0a26534f6e03c32312836c0f9b83aa358ddac0852a7bfd1e50136ea4bc6b6715'),
    'clap-ms-tokenizer.json': (3557853, '0fa4827ec39265089e822a6491293827737093c837ad8fa3ad9f20f2d76308cf'),
}
LICENCES = {'panns-cnn14-mAP0.431': 'CC BY 4.0', 'laion-clap-htsat-unfused': 'Apache 2.0', 'ms-clap-2023': 'MS-PL'}
BLOCK = 1 << 20


class DownloadError(Exception):
    pass


class Cancelled(Exception):
    pass


def download_size(spec, files=FILES):
    return sum(files[name][0] for name in spec.files())


def installed(spec, folder, files=FILES):
    """All of the model's files are present with the expected size (hashes were checked when they were downloaded)."""
    for name in spec.files():
        path = Path(folder) / name
        if not path.is_file() or (name in files and path.stat().st_size != files[name][0]):
            return False
    return True


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as file:
        for block in iter(lambda: file.read(BLOCK), b''):
            digest.update(block)
    return digest.hexdigest()


def download(name, folder, base_url=BASE_URL, files=FILES, progress=lambda done, total: None,
             should_stop=lambda: False, timeout=60):
    """Download one file into `folder`, resuming a previous `.part`; raise DownloadError on a bad checksum."""
    size, expected = files[name]
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target, part = folder / name, folder / (name + '.part')
    done = part.stat().st_size if part.exists() else 0
    if done > size:
        part.unlink()
        done = 0
    if done < size:
        headers = {'User-Agent': 'SongSelector'}
        if done:
            headers['Range'] = f'bytes={done}-'
        with urllib.request.urlopen(urllib.request.Request(base_url + name, headers=headers), timeout=timeout) as response:
            if done and response.status != 206:  # the server ignored the range: start over
                done = 0
            with open(part, 'ab' if done else 'wb') as file:
                progress(done, size)
                while True:
                    if should_stop():
                        raise Cancelled()
                    block = response.read(BLOCK)
                    if not block:
                        break
                    file.write(block)
                    done += len(block)
                    progress(done, size)
    if sha256(part) != expected:
        part.unlink()  # never resume from bad data
        raise DownloadError(f'{name}: the downloaded file does not match its checksum; try again')
    os.replace(part, target)
    return target


def download_models(specs, folder, base_url=BASE_URL, files=FILES, progress=lambda name, done, total: None,
                    should_stop=lambda: False):
    """Download every missing file of these models. progress(name, bytes done in all, bytes in all).
    Returns the models that are complete afterwards."""
    todo = [name for spec in specs for name in spec.files()
            if not (Path(folder) / name).is_file() or (Path(folder) / name).stat().st_size != files[name][0]]
    total = sum(files[name][0] for name in todo)
    finished = 0
    for name in todo:
        download(name, folder, base_url, files,
                 lambda done, _size, name=name, before=finished: progress(name, before + done, total), should_stop)
        finished += files[name][0]
    return [spec for spec in specs if installed(spec, folder, files)]

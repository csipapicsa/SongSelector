"""Downloads the model files into the models folder.

The files are the ONNX exports made by scripts/export_cnn14_onnx.py, scripts/export_clap_onnx.py and (AllMusicCaps)
docs/research/experiments/clap/amclap_onnx.py. Each model has
its own Hugging Face repo (since 2026-11-20) with a model card naming the source, the changes and the licence
(packaging/models/hf/). The app downloads from the commit that added the files, so a later change to a repo cannot
change what this version downloads. `Model download URL` in the settings points the app at another copy instead: a
web folder serving the files under their names.

Each download goes to `<name>.part` first, resumes where it stopped (HTTP Range), and gets its real name only after
its SHA-256 matches the one below, so a broken or tampered file is never used.

No PyQt5 here; ui/model_download_dialog.py runs this in a thread.
"""
import hashlib
import os
import urllib.request
from pathlib import Path

BUILD_HELP = 'https://github.com/csipapicsa/SongSelector#getting-the-embedding-models'

# Hugging Face repo: (the commit that holds the files, the files)
HUGGING_FACE = {
    'csipapicsa/songselector-cnn14': ('8ebf372b2b1b212865a66f5648144163b8808547', ['cnn14.onnx']),
    'csipapicsa/songselector-clap-laion': ('14bcb104eba2d7c376e2c2e6ae83d21ccb042022',
                                           ['clap-laion-audio.onnx', 'clap-laion-text.onnx',
                                            'clap-laion-tokenizer.json']),
    'csipapicsa/songselector-clap-ms': ('73b59b5999bac9db8a2c15c786759f2005ecf657',
                                        ['clap-ms-audio.onnx', 'clap-ms-text.onnx', 'clap-ms-tokenizer.json']),
    'csipapicsa/songselector-clap-amc': ('b349da373ac4a83a814982453e41693f4272eb62', ['clap-amc-audio.onnx', 'clap-amc-text.onnx',
                                                     'clap-amc-tokenizer.json']),
}
URLS = {name: f'https://huggingface.co/{repo}/resolve/{commit}/{name}'
        for repo, (commit, names) in HUGGING_FACE.items() for name in names}

# name: (size in bytes, SHA-256); the model cards list the same values.
FILES = {
    'cnn14.onnx': (327330336, 'ae868eda6e9734f4722d61fe70e45ce215c316e3fe306023105ff3c0a9e73a32'),
    'clap-laion-audio.onnx': (121612865, '3c736ebc3a05f8cc652b93f2306e4c12eb714aba9e455f2c17541ed63042d55c'),
    'clap-laion-text.onnx': (501449463, '2cebcbe969166aa29db1750c688103cefc474b9ae478d747a3b4faa346ec5bbd'),
    'clap-laion-tokenizer.json': (3558802, '4fd1d86b4f5b53f40a609fcd11c1f34024b735f870a07439d70202b98493661a'),
    'clap-ms-audio.onnx': (126555913, 'e9b5c1cc2e43cd870a3df94535774bd4aed5456f0a7cc8c519a82e80c84b7ff2'),
    'clap-ms-text.onnx': (505456227, '0a26534f6e03c32312836c0f9b83aa358ddac0852a7bfd1e50136ea4bc6b6715'),
    'clap-ms-tokenizer.json': (3557853, '0fa4827ec39265089e822a6491293827737093c837ad8fa3ad9f20f2d76308cf'),
    'clap-amc-audio.onnx': (295550979, '1fb193cbddef664e95303fef3b4cbf0b3c7519b42c61b4bd16f3e86be5c6b378'),
    'clap-amc-text.onnx': (437419780, 'b75c45c5d7581ac9899b01c1def30019782ba777f9aa6ee2da78dbd5a1de2068'),
    'clap-amc-tokenizer.json': (710932, '46fb1f735006f52c1f9744bb05f7bc1544ec8475955af30396212c7737558d1e'),
}
LICENCES = {'panns-cnn14-mAP0.431': 'CC BY 4.0', 'laion-clap-htsat-unfused': 'Apache 2.0', 'ms-clap-2023': 'MS-PL',
            'mtg-allmusiccaps-all-layers': 'CC BY-NC-SA 4.0, non-commercial'}
BLOCK = 1 << 20


class DownloadError(Exception):
    pass


class Cancelled(Exception):
    pass


def download_size(spec, files=FILES):
    return sum(files[name][0] for name in spec.files())


# One model file in the models folder. A file the app downloaded had its SHA-256 checked then; any other (copied in,
# or in a folder chosen with Models folder...) is checked once in the background (check_file). `checked` keeps the
# results, {path: [size, mtime_ns, ok]}: a file changed since its check is unchecked again.
OK, UNCHECKED, MISSING, WRONG_SIZE, WRONG_CHECKSUM = 'ok', 'unchecked', 'missing', 'wrong size', 'wrong checksum'
# A whole model: every file ok; usable while its checksums are still being checked; or what is wrong with it.
INSTALLED, CHECKING, NOT_INSTALLED, INCOMPLETE, DAMAGED = 'installed', 'checking', 'not installed', 'incomplete', \
    'damaged'


def file_state(folder, name, files=FILES, checked=None):
    path = Path(folder) / name
    try:
        stat = path.stat()
    except OSError:
        return MISSING
    if not path.is_file():
        return MISSING
    if name not in files:
        return OK  # no checksum known for it: being there is all that can be checked
    if stat.st_size != files[name][0]:
        return WRONG_SIZE
    record = (checked or {}).get(str(path))
    if record and list(record[:2]) == [stat.st_size, stat.st_mtime_ns]:
        return OK if record[2] else WRONG_CHECKSUM
    return UNCHECKED


def file_states(spec, folder, files=FILES, checked=None):
    """{file name: state} of the model's files, in the model's order."""
    return {name: file_state(folder, name, files, checked) for name in spec.files()}


def model_state(states):
    values = set(states.values())
    if values <= {OK}:
        return INSTALLED
    if values <= {OK, UNCHECKED}:
        return CHECKING
    if values & {WRONG_SIZE, WRONG_CHECKSUM}:
        return DAMAGED
    return NOT_INSTALLED if values == {MISSING} else INCOMPLETE


def usable(states):
    """All files there with the right size and none failed its checksum: the model can be used (also while the
    checksums are still being checked)."""
    return all(state in (OK, UNCHECKED) for state in states.values())


def problems(states):
    """'clap-ms-text.onnx: missing, cnn14.onnx: wrong checksum'; '' if there are none."""
    return ', '.join(f'{name}: {state}' for name, state in states.items() if state in (MISSING, WRONG_SIZE,
                                                                                       WRONG_CHECKSUM))


def installed(spec, folder, files=FILES, checked=None):
    """The model's files are all there with the expected size, and none failed its checksum."""
    return usable(file_states(spec, folder, files, checked))


def check_file(path, name, files=FILES):
    """Compute the file's SHA-256 (slow: hundreds of MB) and compare it: the record for `checked`, or None if the file
    changed meanwhile (e.g. it was still being copied)."""
    path = Path(path)
    before = path.stat()
    ok = sha256(path) == files[name][1]
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        return None
    return [after.st_size, after.st_mtime_ns, ok]


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as file:
        for block in iter(lambda: file.read(BLOCK), b''):
            digest.update(block)
    return digest.hexdigest()


def url(name, base_url=''):
    """Where `name` is downloaded from: `base_url` + name if set (a web folder), else its Hugging Face repo."""
    return base_url + name if base_url else URLS[name]


def download(name, folder, base_url='', files=FILES, progress=lambda done, total: None,
             should_stop=lambda: False, timeout=60):
    """Download one file into `folder`, resuming a previous `.part`; raise DownloadError on a bad checksum.
    base_url: a web folder serving the files under their names; empty for the Hugging Face repos."""
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
        with urllib.request.urlopen(urllib.request.Request(url(name, base_url), headers=headers),
                                    timeout=timeout) as response:
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


def download_models(specs, folder, base_url='', files=FILES, progress=lambda name, done, total: None,
                    should_stop=lambda: False, checked=None, on_checked=lambda path, record: None):
    """Download every file of these models that is missing, has the wrong size or failed its checksum.
    progress(name, bytes done in all, bytes in all); on_checked(path, record) for each downloaded file (its checksum
    was checked by the download). Returns the models that are complete afterwards."""
    checked = dict(checked or {})
    todo = [name for spec in specs for name, state in file_states(spec, folder, files, checked).items()
            if state in (MISSING, WRONG_SIZE, WRONG_CHECKSUM)]
    total = sum(files[name][0] for name in todo)
    finished = 0
    for name in todo:
        target = download(name, folder, base_url, files,
                          lambda done, _size, name=name, before=finished: progress(name, before + done, total),
                          should_stop)
        stat = target.stat()
        checked[str(target)] = [stat.st_size, stat.st_mtime_ns, True]
        on_checked(str(target), checked[str(target)])
        finished += files[name][0]
    return [spec for spec in specs if installed(spec, folder, files, checked)]

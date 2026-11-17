"""Cover art of a track: the picture embedded in the file, else an image file next to it (cover.jpg, folder.jpg...).

Returns the image's bytes as stored (JPEG / PNG); scaling them to thumbnails is the UI's job (Qt). No Qt here.
"""
import hashlib
import os

from mutagen import File as MutagenFile
from mutagen import MutagenError
from mutagen.id3 import ID3

from songselector.core.traktor_collection import canonical_path

# Image files next to the audio file, in the order they are tried (Windows file names ignore case).
FOLDER_NAMES = ('cover.jpg', 'cover.jpeg', 'cover.png', 'folder.jpg', 'folder.jpeg', 'folder.png', 'front.jpg',
                'front.png', 'albumart.jpg')
FRONT_COVER = 3  # picture type "Cover (front)" in ID3 and FLAC
MAX_COVER_BYTES = 20 * 1024 * 1024  # larger "covers" are not images worth reading


def embedded_cover(path):
    """Bytes of the embedded picture (the front cover if there are several), or None."""
    try:
        audio = MutagenFile(str(path))
    except (MutagenError, OSError, ValueError):
        audio = None
    if audio is None:  # e.g. an MP3 whose audio frames mutagen cannot identify: its ID3 tag may still be readable
        try:
            audio = type('Tagged', (), {'tags': ID3(str(path))})()
        except (MutagenError, OSError, ValueError):
            return None
    pictures = []  # (picture type, bytes)
    for picture in getattr(audio, 'pictures', None) or []:  # FLAC, Ogg with METADATA_BLOCK_PICTURE
        pictures.append((picture.type, picture.data))
    tags = getattr(audio, 'tags', None)
    if tags is not None:
        if hasattr(tags, 'getall'):  # ID3: MP3, WAV, AIFF
            pictures += [(frame.type, frame.data) for frame in tags.getall('APIC')]
        elif 'covr' in tags:  # MP4 / M4A
            pictures += [(FRONT_COVER, bytes(cover)) for cover in tags['covr']]
    pictures = [(kind, data) for kind, data in pictures if data]
    if not pictures:
        return None
    front = [data for kind, data in pictures if kind == FRONT_COVER]
    return (front or [data for _kind, data in pictures])[0]


def folder_cover(path):
    """Bytes of cover.jpg / folder.jpg / ... in the file's folder, or None."""
    folder = os.path.dirname(str(path))
    try:
        names = {name.lower(): name for name in os.listdir(folder)}
    except OSError:
        return None
    for wanted in FOLDER_NAMES:
        name = names.get(wanted)
        if name is None:
            continue
        image = os.path.join(folder, name)
        try:
            if os.path.getsize(image) > MAX_COVER_BYTES:
                continue
            with open(image, 'rb') as handle:
                return handle.read()
        except OSError:
            continue
    return None


def find_cover(path):
    """The track's cover: embedded first, else an image file in its folder; None if there is none."""
    return embedded_cover(path) or folder_cover(path)


def cache_keys(path):
    """(cover key, no-cover key): names for the track's cached thumbnail and for its "has no cover" marker, or
    (None, None) if the file cannot be read. The cover key changes with the file (e.g. a new embedded picture); the
    no-cover key also with its folder, so a cover.jpg added later is found. (A found cover does not depend on the
    folder: any new file there, even the cache folder itself, would otherwise make every cover in it stale.)"""
    try:
        stat = os.stat(path)
        folder = os.stat(os.path.dirname(str(path)) or '.')
    except OSError:
        return None, None
    file_text = f'{canonical_path(path)}|{stat.st_size}|{stat.st_mtime_ns}'
    return (hashlib.sha1(file_text.encode('utf-8')).hexdigest(),
            hashlib.sha1(f'{file_text}|{folder.st_mtime_ns}'.encode()).hexdigest())

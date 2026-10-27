"""Write user-edited Artist / Title / Genre into an audio file's own tags.

This is the only place the app writes to audio files. It changes just these
three tags and leaves every other tag (key, BPM, rating, comment, artwork, ...)
and the audio data untouched. The Traktor collection is never written.
"""
from pathlib import Path

from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError, TCON, TIT2, TPE1
from mutagen.wave import WAVE

EDITABLE_TAGS = ('Artist', 'Title', 'Genre')
_ID3_FRAMES = {'Artist': TPE1, 'Title': TIT2, 'Genre': TCON}
_VORBIS_KEYS = {'Artist': 'artist', 'Title': 'title', 'Genre': 'genre'}


def _apply_id3(tags, values):
    for name, value in values.items():
        frame = _ID3_FRAMES[name]
        tags.delall(frame.__name__)
        if value:
            tags.add(frame(encoding=3, text=[value]))


def _id3_version(tags):
    # Keep the file's ID3 version: Traktor and older players often expect v2.3.
    return 4 if tags.version >= (2, 4, 0) else 3


def write_tags(path, **values):
    """Write e.g. write_tags(path, Artist='A', Genre='Breaks'); an empty string removes a tag.

    Raises ValueError for unknown fields or unsupported files, OSError/mutagen errors on failure.
    """
    unknown = set(values) - set(EDITABLE_TAGS)
    if unknown:
        raise ValueError(f'Not an editable tag: {", ".join(sorted(unknown))}')
    values = {name: (value or '').strip() for name, value in values.items()}
    path = Path(path)
    if not path.is_file():
        raise ValueError(f'File not found: {path}')
    extension = path.suffix.lower()
    if extension == '.mp3':
        try:
            tags = ID3(str(path))
            version = _id3_version(tags)
        except ID3NoHeaderError:
            tags, version = ID3(), 3
        _apply_id3(tags, values)
        tags.save(str(path), v2_version=version)
    elif extension == '.wav':
        audio = WAVE(str(path))
        if audio.tags is None:
            audio.add_tags()
            version = 3
        else:
            version = _id3_version(audio.tags)
        _apply_id3(audio.tags, values)
        audio.save(v2_version=version)
    elif extension == '.flac':
        audio = FLAC(str(path))
        for name, value in values.items():
            key = _VORBIS_KEYS[name]
            if value:
                audio[key] = [value]
            elif key in audio:
                del audio[key]
        audio.save()
    else:
        raise ValueError(f'Cannot write tags to {extension or "this"} files')

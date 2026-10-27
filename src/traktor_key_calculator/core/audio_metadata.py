"""Read audio metadata without changing tags or audio files."""
from pathlib import Path
from mutagen.id3 import ID3, ID3NoHeaderError
from mutagen.flac import FLAC
from mutagen.wave import WAVE
from traktor_key_calculator.config import AudioMetadata
from traktor_key_calculator.core.key_formats import parse_key, parse_bpm


def get_file_extension(path):
    return Path(path).suffix.lstrip('.').lower()


def popm_byte_to_stars(value):
    value = int(value)
    if value <= 0:
        return None
    return 1 if value <= 32 else 2 if value <= 96 else 3 if value <= 162 else 4 if value <= 226 else 5


def _rating(tags):
    frames = tags.getall('POPM')
    if not frames:
        return None
    frame = next((f for f in frames if 'traktor' in f.email.lower()),
                 next((f for f in frames if 'windows media player' in f.email.lower()), frames[0]))
    return popm_byte_to_stars(frame.rating)


def get_mp3_rating(filepath):
    try:
        return _rating(ID3(str(filepath)))
    except ID3NoHeaderError:
        return None


def get_flac_rating(tags):
    for field in ('rating wmp', 'rating', 'fmps_rating'):
        values = tags.get(field)
        if not values:
            continue
        try:
            value = float(values[0])
            if field == 'fmps_rating' or value <= 1:
                return round(value * 5)
            return round(value / 51) if value > 5 else round(value)
        except (ValueError, TypeError):
            continue
    return None


def _read_id3(tags, metadata):
    for attribute, frame in (('title', 'TIT2'), ('artist', 'TPE1'), ('album', 'TALB'), ('genre', 'TCON')):
        value = str(tags.get(frame, '')).strip()
        setattr(metadata, attribute, value or None)
    # Only the main comment (no description); described COMM frames hold other data,
    # e.g. iTunes' iTunNORM loudness values.
    comments = [frame for frame in tags.getall('COMM') if not frame.desc]
    if comments:
        comment = next((f for f in comments if f.lang.lower() in ('eng', 'xxx')), comments[0])
        metadata.comment = ' / '.join(comment.text) or None
    user_tags = {frame.desc.casefold(): str(frame) for frame in tags.getall('TXXX')}
    keys = [str(tags.get('TKEY', ''))] + [user_tags.get(k) for k in ('initialkey', 'initial key', 'key')]
    metadata.key = next((k for k in keys if parse_key(k)), next((k for k in keys if k), None))
    bpms = [str(tags.get('TBPM', ''))] + [user_tags.get(k) for k in ('bpm', 'tempo')]
    metadata.bpm = next((b for b in bpms if parse_bpm(b)), None)
    metadata.rating = _rating(tags)


def extract_wav_metadata(filepath):
    metadata = AudioMetadata()
    try:
        tags = WAVE(str(filepath)).tags
        if tags is not None:
            _read_id3(tags, metadata)
    except Exception as error:
        metadata.error = str(error)
    return metadata


def extract_audio_metadata(filepath):
    metadata = AudioMetadata()
    filepath = Path(filepath)
    try:
        extension = filepath.suffix.lower()
        if extension == '.mp3':
            try:
                _read_id3(ID3(str(filepath)), metadata)
            except ID3NoHeaderError:
                pass
        elif extension == '.wav':
            return extract_wav_metadata(filepath)
        elif extension == '.flac':
            tags = FLAC(str(filepath))
            for attribute in ('title', 'artist', 'album', 'genre', 'comment'):
                setattr(metadata, attribute, (tags.get(attribute) or [None])[0])
            metadata.key = next(((tags.get(k) or [None])[0] for k in ('initialkey', 'key')
                                 if parse_key((tags.get(k) or [None])[0])), None)
            metadata.bpm = (tags.get('bpm') or [None])[0]
            metadata.rating = get_flac_rating(tags)
    except Exception as error:
        metadata.error = str(error)
    return metadata

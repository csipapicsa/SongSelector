"""The DJ programs whose libraries the app reads, and their priority.

Each track's key, BPM, colour and rating can come from several programs. The *primary* program (a setting;
automatic = the first one found, in PROGRAMS order) decides a track it knows; for a track it does not know,
the next program that does decides. The others only fill values that are still empty (core/traktor_sync.py).
Rekordbox is not here yet: only its playlists are read so far.
"""
TRAKTOR, MIXXX = 'traktor', 'mixxx'
PROGRAMS = (TRAKTOR, MIXXX)  # the automatic order
NAMES = {TRAKTOR: 'Traktor', MIXXX: 'Mixxx'}
# How a value's source is labelled in the Key_Source / BPM_Source / Color_Source columns.
SOURCES = {TRAKTOR: 'Traktor collection', MIXXX: 'Mixxx library'}
AUTOMATIC = 'auto'


def priority(primary):
    """Programs in priority order: the primary first, then the rest in the automatic order."""
    return [primary] + [program for program in PROGRAMS if program != primary] if primary in PROGRAMS \
        else list(PROGRAMS)


def resolve_primary(setting, available):
    """The primary program for a setting ('auto', 'traktor', 'mixxx') and the programs whose library was found
    (a set). Automatic: the first found, else Traktor."""
    if setting in PROGRAMS:
        return setting
    return next((program for program in PROGRAMS if program in available), TRAKTOR)

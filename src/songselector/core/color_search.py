"""Named colour families and search-bar color filters.

Families 1-7 are Traktor's colours; 8-11 come from file tags and from the exact colours of other programs
(core/track_colors.py: Mixxx's #00FFFF is cyan). A filter matches a track by the family of its colour.
"""
import re
from dataclasses import dataclass, field

from songselector.core.track_colors import family

COLOR_NAMES = {0: 'none', 1: 'red', 2: 'orange', 3: 'yellow', 4: 'green',
               5: 'blue', 6: 'indigo', 7: 'violet', 8: 'pink', 9: 'brown', 10: 'cyan', 11: 'grey'}
COLOR_ALIASES = {name: number for number, name in COLOR_NAMES.items()}
COLOR_ALIASES.update({'purple':7, 'magenta':7, 'uncolored':0, 'uncoloured':0,
                      'no color':0, 'no colour':0, 'aqua':10, 'turquoise':10, 'teal':10,
                      'gray':11, 'white':11, 'black':11})
COLOR_HELP = 'red, orange, yellow, green, cyan (aqua), blue, indigo, violet (purple), pink, brown, grey, none'
# Search-bar keywords: color: filters the Traktor color, sscolor: the Song Selector color.
TRAKTOR_COLOR_KEYWORDS = ('color', 'colour')
SS_COLOR_KEYWORDS = ('sscolor', 'sscolour')


def _color_token(keywords):
    # Tokens start at a word boundary; ordinary title text like "discolor:blue" stays text.
    return re.compile(r'(?<!\S)(?P<exclude>-?)(?:' + '|'.join(keywords) +
                      r')\s*:\s*(?P<values>[^\s,|]*(?:\s*[,|]\s*[^\s,|]*)*)', re.IGNORECASE)


COLOR_TOKEN = _color_token(TRAKTOR_COLOR_KEYWORDS)
SS_COLOR_TOKEN = _color_token(SS_COLOR_KEYWORDS)


def parse_color_values(value):
    colors = set()
    for part in re.split(r'[,|]', str(value)):
        name = part.strip().casefold()
        if name in COLOR_ALIASES:
            colors.add(COLOR_ALIASES[name])
        elif name.isdigit() and int(name) in COLOR_NAMES:
            colors.add(int(name))
        else:
            return set(), f'Unknown color "{part.strip()}". Choose: {COLOR_HELP}.'
    return colors, ''


def color_id(value):
    """Family number of a stored colour (a family number or an exact '#RRGGBB'); 0 = none, None = not a colour."""
    return family(value)


@dataclass
class ColorSearch:
    text: str = ''
    included: set = field(default_factory=set)
    excluded: set = field(default_factory=set)
    has_included: bool = False
    error: str = ''

    def matches(self, value):
        if self.error:
            return False
        number = color_id(value)
        return (not self.has_included or number in self.included) and number not in self.excluded


def parse_color_search(text, token=COLOR_TOKEN):
    """Split color tokens (color: by default, or SS_COLOR_TOKEN) from plain search text."""
    result = ColorSearch()
    def consume(match):
        colors, error = parse_color_values(match.group('values'))
        result.error = result.error or error
        if match.group('exclude'):
            result.excluded.update(colors)
        else:
            result.has_included = True
            result.included.update(colors)
        return ''
    remaining = token.sub(consume, text).strip()
    result.text = re.sub(r'[ \t]+', ' ', remaining) if result.has_included or result.excluded or result.error else remaining
    return result


def replace_color_filter(text, selected):
    """Replace positive color tokens, retaining plain text and exclusions."""
    remaining = COLOR_TOKEN.sub(lambda match: match.group(0) if match.group('exclude') else '', text).strip()
    remaining = re.sub(r'[ \t]+', ' ', remaining)
    names = ','.join(COLOR_NAMES[number] for number in sorted(selected))
    return (remaining + (' color:' + names if names else '')).strip()

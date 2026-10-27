"""Named Traktor category colors and search-bar color filters."""
from dataclasses import dataclass, field
import math
import re

COLOR_NAMES = {0: 'none', 1: 'red', 2: 'orange', 3: 'yellow', 4: 'green',
               5: 'blue', 6: 'indigo', 7: 'violet', 8: 'pink', 9: 'brown'}
COLOR_ALIASES = {name: number for number, name in COLOR_NAMES.items()}
COLOR_ALIASES.update({'purple':7, 'magenta':7, 'uncolored':0, 'uncoloured':0,
                      'no color':0, 'no colour':0})
COLOR_HELP = 'red, orange, yellow, green, blue, indigo, violet (purple), pink, brown, none'
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
    text = str(value).strip().casefold() if value is not None else ''
    if text in ('', 'none', 'nan'):
        return 0
    try:
        number = float(text)
        return int(number) if math.isfinite(number) and number.is_integer() and int(number) in COLOR_NAMES else None
    except (ValueError, TypeError, OverflowError):
        return None


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

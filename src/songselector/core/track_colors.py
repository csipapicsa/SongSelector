"""Track colours from any DJ program: a colour family number, or the program's exact colour.

A track's `Color` value is one of
- a family number (`COLOR_NAMES` in core/color_search.py): Traktor's colours 1-7 and file tags give these;
- an exact colour '#RRGGBB': programs with free colours (Mixxx, and Rekordbox later) give these, so the
  list and the map show the colour the DJ picked.

Search (`color:orange`), filters and smartlists work on families, so an exact colour also belongs to the
family nearest to its hue: Mixxx's #880000 and #FF0000 are both "red", #00FFFF is "cyan".
No Qt here: the core stays importable without a GUI (config.track_qcolor draws these).
"""
import colorsys
import math
import re

NONE, RED, ORANGE, YELLOW, GREEN, BLUE, INDIGO, VIOLET, PINK, BROWN, CYAN, GREY = range(12)
FAMILIES = range(12)
_HEX = re.compile(r'#?([0-9A-Fa-f]{6})')
# Hue bands (degrees, upper bound) of saturated colours. Indigo and brown are never inferred from RGB:
# they are Traktor / tag colours only, and as hues they would split red, orange and blue in unexpected places.
_HUES = ((15, RED), (45, ORANGE), (70, YELLOW), (165, GREEN), (200, CYAN), (255, BLUE), (320, VIOLET),
         (345, PINK), (360, RED))


def hex_color(value):
    """'#RRGGBB' (upper case) for '#rrggbb' / 'rrggbb' text or a 0xRRGGBB integer from a database; else None."""
    if isinstance(value, int) and not isinstance(value, bool):
        return f'#{value:06X}' if 0 <= value <= 0xFFFFFF else None
    match = _HEX.fullmatch(str(value).strip()) if isinstance(value, str) else None
    return '#' + match.group(1).upper() if match else None


def normalize(value):
    """A stored colour as the app keeps it: a family number (0 = none) or '#RRGGBB'; None if not a colour.
    Accepts what tables, CSVs and databases hold: 4, 4.0, '4', '4.0', '#ff8800', None / NaN / '' (= 0)."""
    if value is None:
        return NONE
    if isinstance(value, str):
        text = value.strip()
        if text.startswith('#'):
            return hex_color(text)
        if text.casefold() in ('', 'none', 'nan'):
            return NONE
        value = text
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if math.isnan(number):
        return NONE
    return int(number) if math.isfinite(number) and number.is_integer() and int(number) in FAMILIES else None


def family_of_rgb(text):
    """Family of an exact colour '#RRGGBB', by hue; washed-out and very dark colours are grey."""
    red, green, blue = (int(text[i:i + 2], 16) / 255 for i in (1, 3, 5))
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    hue *= 360
    if value < 0.12 or saturation < 0.15:
        return GREY
    # Light, soft magentas and reds read as pink (Mixxx #FF88FF, Rekordbox #F870F8, #FFC0CB); strong ones do not.
    if value > 0.8 and ((275 <= hue < 345 and saturation < 0.6) or ((hue >= 345 or hue < 15) and saturation < 0.5)):
        return PINK
    return next(family for upper, family in _HUES if hue < upper)


def family(value):
    """Family number (0 = none) of a stored colour; None if it is not a colour."""
    colour = normalize(value)
    if isinstance(colour, str):
        return family_of_rgb(colour)
    return colour


def is_colored(value):
    """Whether a stored colour is an actual colour (not none / not readable)."""
    return bool(family(value))

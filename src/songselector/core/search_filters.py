"""Shared complex-search comparison rules."""
import math
import operator

from songselector.config import MATCH_COLUMN, SPEED_COLUMN, SS_COLOR_COLUMN, SS_RATING_COLUMN
from songselector.core.color_search import color_id, parse_color_values

NUMERIC_COLUMNS = {'Original BPM', 'New BPM', 'BPM', 'Tempo', 'Rating', 'Color', SS_RATING_COLUMN, SS_COLOR_COLUMN,
                   SPEED_COLUMN, MATCH_COLUMN}
# Columns holding a category color number; they also accept color names (blue, red,orange).
COLOR_COLUMNS = {'Color', SS_COLOR_COLUMN}
TEXT_CONDITIONS = ['contains', 'does not contain', 'is', 'is not']
NUMERIC_COMPARISONS = {
    'greater than': operator.gt,
    'less than': operator.lt,
    'at least (>=)': operator.ge,
    'at most (<=)': operator.le,
}
# Speed change to the master tempo (asked 2026-11-17): "no more than X % faster or slower", or more than that.
SPEED_CONDITIONS = {
    'within ± (%)': lambda actual, limit: abs(actual) <= abs(limit),
    'outside ± (%)': lambda actual, limit: abs(actual) > abs(limit),
}
# Before the Active tick (2026-11-27), a row set to this column kept its condition and value but did not filter.
# Saved searches and smartlists may still hold such rows.
NO_COLUMN = 'None'


def active_filters(filters):
    """The rules that filter: ticked Active (rules saved before the tick count as ticked), a value is given and a
    column is chosen."""
    return [f for f in filters if f.get('active', True) and f.get('value') and f.get('column') != NO_COLUMN]


def parse_number(value):
    """128.5, '128,5', '+6.2%' (the Speed change column) -> float; None if it is not a number."""
    try:
        number = float(str(value).strip().rstrip('%').strip().replace(',', '.'))
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def matches_condition(cell, condition, value, column):
    # The Match column has a value only while the List shows description results ('31%', -100 % to 100 %). A Match
    # rule filters those; without a description search it lets every track through instead of hiding them all.
    if column == MATCH_COLUMN and not str(cell or '').strip():
        return True
    if condition in SPEED_CONDITIONS:
        actual, limit = parse_number(cell), parse_number(value)
        return (column == SPEED_COLUMN and actual is not None and limit is not None
                and SPEED_CONDITIONS[condition](actual, limit))
    if condition in NUMERIC_COMPARISONS:
        if column not in NUMERIC_COLUMNS:
            return False
        actual, threshold = parse_number(cell), parse_number(value)
        return actual is not None and threshold is not None and NUMERIC_COMPARISONS[condition](actual, threshold)
    if column in COLOR_COLUMNS and str(value).strip():
        colors, error = parse_color_values(value)
        actual = color_id(cell)
        if error or actual is None:
            return False
        if condition in ('contains', 'is'):
            return actual in colors
        if condition in ('does not contain', 'is not'):
            return actual not in colors
    actual, expected = str(cell).casefold(), str(value).casefold()
    if condition == 'contains':
        return expected in actual
    if condition == 'does not contain':
        return expected not in actual
    if condition == 'is':
        return actual == expected
    if condition == 'is not':
        return actual != expected
    return False

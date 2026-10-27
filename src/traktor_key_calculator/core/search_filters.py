"""Shared complex-search comparison rules."""
import math
import operator
from traktor_key_calculator.config import SS_RATING_COLUMN, SS_COLOR_COLUMN
from traktor_key_calculator.core.color_search import color_id, parse_color_values

NUMERIC_COLUMNS = {'Original BPM', 'New BPM', 'BPM', 'Tempo', 'Rating', 'Color', SS_RATING_COLUMN, SS_COLOR_COLUMN}
# Columns holding a category color number; they also accept color names (blue, red,orange).
COLOR_COLUMNS = {'Color', SS_COLOR_COLUMN}
TEXT_CONDITIONS = ['contains', 'does not contain', 'is', 'is not']
NUMERIC_COMPARISONS = {
    'greater than': operator.gt,
    'less than': operator.lt,
    'at least (>=)': operator.ge,
    'at most (<=)': operator.le,
}


def parse_number(value):
    try:
        number = float(str(value).strip().replace(',', '.'))
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def matches_condition(cell, condition, value, column):
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

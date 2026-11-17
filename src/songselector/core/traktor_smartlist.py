"""Traktor smartlists: parse the query stored in collection.nml and find the tracks it matches.

A smartlist's query looks like  $BPM > 126.000000 & $GENRE % "break" | $COLOR == 5  (SEARCH_EXPRESSION QUERY).
It is evaluated on Traktor's own track records (core.traktor_collection), so the result is what Traktor shows, as far
as the stored values allow.

Grammar (as found in the user's 43 smartlists, 2026-11-17):
    query      := and ('|' and)*            '&' binds tighter than '|' (no smartlist mixes them; an assumption)
    and        := condition ('&' condition)*
    condition  := FIELD OPERATOR VALUE | '(' query ')'
    FIELD      := $BPM $COLOR $RATING $GENRE $COMMENT $ARTIST $TITLE $ALBUM $LABEL $REMIXER $FILEPATH $KEY $TIME
                  $PLAYCOUNT $IMPORTDATE ($PLAYED is per Traktor session: not known outside Traktor)
    OPERATOR   := == <> < <= > >= % (contains) !% (does not contain) ~ (about: within ±1, an assumption)
    VALUE      := "text" | number | mm:ss | TRUE / FALSE | an Open Key like 1m | MONTHS_AGO(n), WEEKS_AGO(n), DAYS_AGO(n)
Text compares without case. A missing number counts as 0, missing text as "".
"""
import re
from dataclasses import dataclass
from datetime import date, timedelta

from songselector.core.key_calculator import KeyCalculator

TEXT_FIELDS = {'GENRE': 'genre', 'COMMENT': 'comment', 'ARTIST': 'artist', 'TITLE': 'title', 'ALBUM': 'album',
               'LABEL': 'label', 'REMIXER': 'remixer', 'FILEPATH': 'path', 'KEY': None}
NUMBER_FIELDS = {'BPM': 'bpm', 'COLOR': 'color', 'RATING': 'rating', 'TIME': 'playtime', 'PLAYCOUNT': 'playcount'}
DATE_FIELDS = {'IMPORTDATE': 'import_date'}
UNSUPPORTED = {'PLAYED': 'played in the current Traktor session (only Traktor knows)'}
OPERATORS = ('==', '<>', '<=', '>=', '!%', '<', '>', '%', '~')
ABOUT = 1.0   # "~": within this much (BPM); Traktor's own tolerance is not stored in the file

_TOKEN = re.compile(r'\s*(?:(\$[A-Z_]+)|("(?:[^"]*)")|(==|<>|<=|>=|!%|<|>|%|~)|([&|()])|([^\s&|()"]+(?:\([^)]*\))?))')
_AGO = re.compile(r'(MONTHS|WEEKS|DAYS|YEARS)_AGO\((\d+)\)', re.IGNORECASE)
_TIME = re.compile(r'(\d+):(\d{1,2})')
_KEYS = KeyCalculator()


class SmartlistError(ValueError):
    """The query cannot be read, or uses something that cannot be evaluated outside Traktor."""


@dataclass
class Condition:
    field: str
    operator: str
    value: object


def tokenize(query):
    tokens, position = [], 0
    query = query or ''
    while position < len(query):
        if query[position:].strip() == '':
            break
        match = _TOKEN.match(query, position)
        if not match or match.end() == position:
            raise SmartlistError(f'cannot read the query at: {query[position:][:20]!r}')
        field, text, operator, symbol, word = match.groups()
        if field:
            tokens.append(('field', field[1:]))
        elif text is not None:
            tokens.append(('value', text[1:-1]))
        elif operator:
            tokens.append(('op', operator))
        elif symbol:
            tokens.append(('sym', symbol))
        else:
            tokens.append(('value', word))
        position = match.end()
    return tokens


def parse(query, today=None):
    """The query as nested ('or' | 'and', [parts]) / Condition; SmartlistError if it cannot be evaluated."""
    tokens = tokenize(query)
    if not tokens:
        raise SmartlistError('the smartlist has no query')
    today = today or date.today()
    position = 0

    def peek():
        return tokens[position] if position < len(tokens) else (None, None)

    def take(kind=None):
        nonlocal position
        token = peek()
        if token[0] is None or (kind and token[0] != kind):
            raise SmartlistError(f'unexpected end or token in the query: {token[1]!r}')
        position += 1
        return token

    def expression():
        parts = [conjunction()]
        while peek() == ('sym', '|'):
            take()
            parts.append(conjunction())
        return parts[0] if len(parts) == 1 else ('or', parts)

    def conjunction():
        parts = [condition()]
        while peek() == ('sym', '&'):
            take()
            parts.append(condition())
        return parts[0] if len(parts) == 1 else ('and', parts)

    def condition():
        if peek() == ('sym', '('):
            take()
            inner = expression()
            if take('sym')[1] != ')':
                raise SmartlistError('a "(" is not closed')
            return inner
        field = take('field')[1].upper()
        if field in UNSUPPORTED:
            raise SmartlistError(f'${field} ({UNSUPPORTED[field]}) cannot be evaluated here')
        if field not in TEXT_FIELDS and field not in NUMBER_FIELDS and field not in DATE_FIELDS:
            raise SmartlistError(f'unknown field ${field}')
        operator = take('op')[1]
        return Condition(field, operator, _value(field, take('value')[1], today))

    result = expression()
    if position != len(tokens):
        raise SmartlistError(f'unexpected {tokens[position][1]!r} in the query')
    return result


def _value(field, text, today):
    if field in DATE_FIELDS:
        ago = _AGO.fullmatch(text.strip())
        if ago:
            unit, count = ago.group(1).upper(), int(ago.group(2))
            days = {'DAYS': 1, 'WEEKS': 7, 'MONTHS': 30, 'YEARS': 365}[unit] * count
            return today - timedelta(days=days)
        parsed = _date(text)
        if parsed is None:
            raise SmartlistError(f'cannot read the date {text!r}')
        return parsed
    if field in NUMBER_FIELDS:
        time = _TIME.fullmatch(text.strip())
        if time:
            return int(time.group(1)) * 60 + int(time.group(2))
        if text.upper() in ('TRUE', 'FALSE'):
            return 1.0 if text.upper() == 'TRUE' else 0.0
        try:
            return float(text)
        except ValueError:
            raise SmartlistError(f'${field} needs a number, not {text!r}') from None
    return text


def _date(text):
    """'2019/12/20' (Traktor's IMPORT_DATE) or '2019-12-20' -> date; None if not a date."""
    match = re.fullmatch(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', str(text or '').strip())
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def open_key(key):
    """Traktor's Open Key notation ('1m', '8d') of a (note, 'major' / 'minor') key; '' if unknown."""
    if not key:
        return ''
    try:
        return str(_KEYS.camelot_to_open_key(_KEYS.get_harmonic_key(key[0], key[1])) or '')
    except (KeyError, TypeError, ValueError):
        return ''


def _field(record, field):
    if field == 'KEY':
        return open_key(record.get('key')).casefold()
    if field in TEXT_FIELDS:
        return str(record.get(TEXT_FIELDS[field]) or '').casefold()
    if field in DATE_FIELDS:
        return _date(record.get(DATE_FIELDS[field]))
    try:
        return float(record.get(NUMBER_FIELDS[field]) or 0)
    except (TypeError, ValueError):
        return 0.0


def _compare(left, operator, right):
    if operator in ('%', '!%') and not isinstance(left, str):
        left, right = ('' if left is None else f'{left:g}' if isinstance(left, float) else str(left)), str(right)
    if operator == '%':
        return right in left
    if operator == '!%':
        return right not in left
    if operator == '~':
        return isinstance(left, float) and abs(left - right) <= ABOUT
    if left is None:  # a date the track does not have
        return operator == '<>'
    return {'==': left == right, '<>': left != right, '<': left < right, '<=': left <= right,
            '>': left > right, '>=': left >= right}[operator]


def matches(record, tree):
    """Whether a collection record (core.traktor_collection) fulfils the parsed query."""
    if isinstance(tree, Condition):
        value = tree.value.casefold() if isinstance(tree.value, str) else tree.value
        return _compare(_field(record, tree.field), tree.operator, value)
    kind, parts = tree
    if kind == 'and':
        return all(matches(record, part) for part in parts)
    return any(matches(record, part) for part in parts)


def smartlist_paths(records, query, today=None):
    """File paths of the records the query matches, in the collection's order. SmartlistError if it cannot be
    evaluated. records: iterable of collection records ({'path', 'bpm', 'genre', ...})."""
    tree = parse(query, today)
    return [record['path'] for record in records if matches(record, tree)]

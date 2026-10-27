"""Application colour themes (Qt Fusion style with a dark or light palette).

Status messages use status_style(kind) instead of fixed colours, so they stay
readable on both backgrounds.
"""
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

THEMES = ('dark', 'light')
DEFAULT_THEME = 'dark'

_DARK = {
    QPalette.Window: '#2b2d30', QPalette.WindowText: '#dfe1e5',
    QPalette.Base: '#1e1f22', QPalette.AlternateBase: '#26282b',
    QPalette.ToolTipBase: '#3c3f41', QPalette.ToolTipText: '#dfe1e5',
    QPalette.Text: '#dfe1e5', QPalette.PlaceholderText: '#8c9096',
    QPalette.Button: '#3c3f41', QPalette.ButtonText: '#dfe1e5',
    QPalette.BrightText: '#ff6b68', QPalette.Link: '#589df6',
    QPalette.Highlight: '#2f65ca', QPalette.HighlightedText: '#ffffff',
    QPalette.Light: '#4a4d50', QPalette.Midlight: '#3c3f41', QPalette.Mid: '#323437',
    QPalette.Dark: '#1b1c1e', QPalette.Shadow: '#111213',
}
_DARK_DISABLED = {QPalette.WindowText: '#6f737a', QPalette.Text: '#6f737a', QPalette.ButtonText: '#6f737a'}

# Status message colours per theme: info (neutral), ok, warning, error.
_STATUS = {
    'dark': {'info': '', 'ok': '#6fcf73', 'warning': '#f0b45a', 'error': '#ff7b72'},
    'light': {'info': '', 'ok': '#1a7f37', 'warning': '#b35900', 'error': '#cf222e'},
}
_current = DEFAULT_THEME


def apply_theme(name, application=None):
    """Apply 'dark' or 'light' to the whole application (works while it runs)."""
    global _current
    application = application or QApplication.instance()
    _current = name if name in THEMES else DEFAULT_THEME
    application.setStyle('Fusion')
    if _current == 'dark':
        palette = QPalette()
        for role, colour in _DARK.items():
            palette.setColor(role, QColor(colour))
        for role, colour in _DARK_DISABLED.items():
            palette.setColor(QPalette.Disabled, role, QColor(colour))
    else:
        palette = application.style().standardPalette()
    application.setPalette(palette)
    return _current


def current_theme():
    return _current


def dim_text_colour():
    """Text colour of de-emphasised rows (e.g. library rows already on the playlist)."""
    from PyQt5.QtGui import QColor
    return QColor('#6f737a') if _current == 'dark' else QColor('#9a9a9a')


def row_tint_alpha():
    """Opacity of the category/key colour tint behind a row; dark backgrounds need more."""
    return 55 if _current == "dark" else 40


def status_style(kind='info', bold=None):
    """Style sheet for a status message: kind is info, ok, warning or error."""
    colour = _STATUS[_current].get(kind, '')
    bold = kind in ('ok', 'error') if bold is None else bold
    return (f'color: {colour}; ' if colour else '') + f'font-weight: {"bold" if bold else "normal"};'

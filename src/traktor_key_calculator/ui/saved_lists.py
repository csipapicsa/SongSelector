"""
saved_lists.py
What the Browser tab does: show a collection entry, playlist or smartlist in the List
view; load playlists and smartlists into the Playlist tab; save, rename, duplicate and
delete them. Mixed into the main window (TraktorKeyCalculator), whose state it uses.

Playlists keep their tracks in order (the "#" column). Smartlists keep Complex Search
rows and always list the tracks that match them now.
"""
import os
import sqlite3

from PyQt5.QtWidgets import QDialog, QInputDialog, QLineEdit, QMenu, QMessageBox

from traktor_key_calculator.config import FIELD_LABELS, HEADER_INDEX, POSITION_COLUMN
from traktor_key_calculator.core.library_store import PLAYLIST, SMARTLIST
from traktor_key_calculator.core.search_filters import active_filters
from traktor_key_calculator.core.traktor_collection import canonical_path
from traktor_key_calculator.ui.advanced_search_dialog import AdvancedSearchDialog
from traktor_key_calculator.ui.list_browser import (COLLECTION_GROUPS, ORDERED_KINDS, SAVED_KINDS, TRACK_SOURCES,
                                                     TRAKTOR, node_label)
from traktor_key_calculator.ui.theme import status_style
from traktor_key_calculator.ui.tree_widgets import audio_paths, dragged_tracks

POSITION = HEADER_INDEX[POSITION_COLUMN]
PATH = HEADER_INDEX['Path']


class SavedListsMixin:
    list_source = None          # Browser entry the List view shows; None: all tracks
    _source_positions = {}      # playlist shown: canonical path -> position (1, 2, ...)
    _source_rules = ()          # smartlist shown: its active rows
    _source_column = None       # artist/album/genre shown: that column
    _sort_before_source = None  # List sort to go back to after a playlist (sorted by #)

    def _init_browser(self):
        self.list_browser.node_selected.connect(self.show_list_source)
        self.list_browser.node_activated.connect(self.load_into_playlist)
        self.list_browser.tracks_dropped.connect(self.add_tracks_to_saved_playlist)
        self.list_browser.menu_requested.connect(self._browser_menu)
        self.source_clear_button.clicked.connect(lambda: self.show_list_source(None))
        self.refresh_saved_lists()

    def _report(self, message, level='ok'):
        self.status_label.setStyleSheet(status_style(level))
        self.status_label.setText(message)

    def refresh_saved_lists(self):
        try:
            self.list_browser.set_lists(self.library_store.saved_lists())
        except sqlite3.Error as error:
            self._report(f'Could not read the saved playlists: {error}', 'error')

    # -- the List view shows one entry ---------------------------------------

    def show_list_source(self, node):
        """Show only the tracks of a Browser entry in the List view; None or All Tracks: all."""
        if node is not None and node.get('kind') not in TRACK_SOURCES - {'all'}:
            node = None
        was_playlist = bool(self.list_source and self.list_source['kind'] in ORDERED_KINDS)
        self.list_source = node
        self._resolve_source()
        is_playlist = bool(self.list_source and self.list_source['kind'] in ORDERED_KINDS)
        self._apply_source_positions()
        if is_playlist and not was_playlist:
            self._sort_before_source = (self.candidate_tree.sort_column, self.candidate_tree.sort_order)
            self.sort_by_column(POSITION, True)  # the set order
        elif was_playlist and not is_playlist and self._sort_before_source:
            self.sort_by_column(*self._sort_before_source)
        self.list_browser.select_node(self.list_source)
        self.filter_items()

    def _resolve_source(self):
        node = self.list_source
        self._source_positions, self._source_rules, self._source_column = {}, (), None
        if node is None:
            return
        if node['kind'] in COLLECTION_GROUPS:
            self._source_column = HEADER_INDEX[COLLECTION_GROUPS[node['kind']][1]]
            return
        if node['kind'] == TRAKTOR:
            keys = self._traktor_keys(node)
            if keys is None:
                self.list_source = None
            else:
                self._source_positions = {key: position for position, key in enumerate(keys, start=1)}
            return
        try:
            saved = self.library_store.saved_list(node['name'])
            if saved is None or saved['kind'] != node['kind']:
                self.list_source = None
            elif node['kind'] == PLAYLIST:
                keys = self.library_store.playlist_keys(node['name'])
                self._source_positions = {key: position for position, key in enumerate(keys, start=1)}
            else:
                self._source_rules = active_filters(saved['rules'] or [])
        except sqlite3.Error as error:
            self.list_source = None
            self._report(f'Could not read {node_label(node)}: {error}', 'error')

    def _in_source(self, item, key):
        node = self.list_source
        if node is None:
            return True
        if node['kind'] in ORDERED_KINDS:
            return key in self._source_positions
        if node['kind'] == SMARTLIST:
            return self._matches_rules(item, self._source_rules)
        return item.text(self._source_column).strip() == node['name']

    def _apply_source_positions(self):
        """Fill the List's # column (playlist shown) and the bar above the List."""
        tree = self.candidate_tree
        shown = 0
        # Qt would re-sort after every change while sorted by #: once, afterwards
        tree.setSortingEnabled(False)
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            position = self._source_positions.get(canonical_path(item.text(PATH)))
            item.setText(POSITION, str(position) if position else '')
            shown += position is not None
        tree.setSortingEnabled(True)
        node = self.list_source
        self.source_bar.setVisible(node is not None)
        if node is None:
            return
        text = f'Showing {node_label(node)}'
        if node['kind'] == SMARTLIST:
            rules = '; '.join(f"{rule['column']} {rule['condition']} {rule['value']}" for rule in self._source_rules)
            text += f' ({rules or "no rules: all tracks"})'
        missing = len(self._source_positions) - shown
        if missing > 0:
            text += f'; {missing} of its tracks are not in the library list'
        self.source_label.setText(text)

    # -- the Playlist tab ------------------------------------------------------

    def playlist_changed(self):
        """Rows were moved within the Playlist tab."""
        error = self._save_playlist()
        if error:
            self._report(error, 'error')

    def add_paths_to_playlist(self, paths, index=None):
        """Insert library tracks (dragged from the List) at row `index`; tracks already on
        the playlist stay where they are."""
        rows = self._rows_by_path()
        present = {canonical_path(path) for path in self.playlist_paths}
        index = self.playlist_tree.topLevelItemCount() if index is None else index
        added = 0
        for path in paths:
            key = canonical_path(path)
            if key in rows and key not in present:
                self._add_to_playlist(rows[key], index + added)
                present.add(key)
                added += 1
        error = self._save_playlist()
        self.filter_items()
        self._report(error or f'Added {added} track(s) to the playlist', 'error' if error else 'ok')
        return added

    def _node_records(self, node):
        """Tracks of a Browser entry, in order: a playlist's set order, else as the List sorts them."""
        rows = self._rows_by_path()
        if node['kind'] == TRAKTOR:
            keys = self._traktor_keys(node) or []
            stored = self.library_store.tracks([key for key in keys if key not in rows])
            return [rows.get(key, stored.get(key)) for key in keys if key in rows or key in stored]
        if node['kind'] == PLAYLIST:
            stored = {canonical_path(record['File_Path']): record
                      for record in self.library_store.load_playlist(node['name'])}
            keys = self.library_store.playlist_keys(node['name'])
            return [rows.get(key, stored.get(key)) for key in keys if key in rows or key in stored]
        if node['kind'] == SMARTLIST:
            saved = self.library_store.saved_list(node['name'])
            rules = active_filters(saved['rules'] or []) if saved else None
            if rules is None:
                return []
            match = lambda item: self._matches_rules(item, rules)
        elif node['kind'] in COLLECTION_GROUPS:
            column = HEADER_INDEX[COLLECTION_GROUPS[node['kind']][1]]
            match = lambda item: item.text(column).strip() == node['name']
        else:
            match = lambda item: True
        records = []
        for index in range(self.candidate_tree.topLevelItemCount()):
            item = self.candidate_tree.topLevelItem(index)
            key = canonical_path(item.text(PATH))
            if key in rows and match(item):
                records.append(rows[key])
        return records

    def load_into_playlist(self, node):
        """Put the tracks of a playlist, smartlist or collection entry into the Playlist tab."""
        try:
            records = self._node_records(node)
        except sqlite3.Error as error:
            self._report(f'Could not read {node_label(node)}: {error}', 'error')
            return False
        if self.playlist_tree.topLevelItemCount():
            answer = self._ask_replace_or_add(node, len(records))
            if answer is None:
                return False
            if answer == 'replace':
                self.playlist_tree.clear()
                self.playlist_paths.clear()
        for record in records:
            self._add_to_playlist(record)
        error = self._save_playlist()
        self.left_tabs.setCurrentWidget(self.playlist_page)
        self.filter_items()
        self._report(error or f'Loaded {node_label(node)} into the Playlist tab', 'error' if error else 'ok')
        return True

    # -- Traktor's playlists --------------------------------------------------

    def refresh_traktor_playlists(self):
        self.list_browser.set_traktor_playlists(self.importer.collection.playlists)
        source = self.list_source
        if source and source['kind'] == TRAKTOR:
            self.show_list_source(source)  # Traktor saved: its playlist may have changed

    def _traktor_entry(self, node):
        entries, found = self.importer.collection.playlists, None
        for name in node.get('path', []):
            found = next((entry for entry in entries if entry['name'] == name), None)
            if found is None:
                return None
            entries = found.get('children', [])
        return found if found is not None and found['type'] == 'PLAYLIST' else None

    def _traktor_keys(self, node):
        """Canonical paths of a Traktor playlist's tracks in order (each once), or None if it is gone."""
        entry = self._traktor_entry(node)
        if entry is None:
            return None
        return list(dict.fromkeys(key for key in map(canonical_path, entry['tracks']) if key))

    def _traktor_missing(self, node):
        """Files of a Traktor playlist that are not in the library list but exist on disk."""
        entry = self._traktor_entry(node) or {'tracks': []}
        rows = self._rows_by_path()
        return [path for path in dict.fromkeys(entry['tracks'])
                if canonical_path(path) not in rows and os.path.isfile(path)]

    def import_traktor_missing(self, node):
        missing = self._traktor_missing(node)
        if missing:
            self.import_audio_files(missing, keep_view=True)
            self.show_list_source(self.list_source)
        else:
            self._report(f'All files of {node_label(node)} that exist are in the library')

    def copy_traktor_playlist(self, node):
        """Save a Traktor playlist as one of the app's playlists (editable); its files that are
        not in the library yet are imported first."""
        name = self._ask_name('Copy to my playlists', node['name'])
        if not name or not self._free_name(name, replace_kind=PLAYLIST):
            return None
        missing = self._traktor_missing(node)
        if missing:
            self.import_audio_files(missing, keep_view=True)
        records = self._node_records(node)
        if self._saved(self.library_store.save_playlist, name, records):
            return None
        copy = {'kind': PLAYLIST, 'name': name}
        self._after_change(copy)
        skipped = len(self._traktor_keys(node) or []) - len(records)
        self._report(f'Copied {len(records)} tracks to playlist "{name}"' +
                     (f'; {skipped} files not found' if skipped else ''))
        return copy

    def _ask_replace_or_add(self, node, count):
        """'replace', 'add' or None (cancelled) for loading into a non-empty Playlist tab."""
        box = QMessageBox(QMessageBox.Question, 'Load into the Playlist',
                          f'Load {node_label(node)} ({count} tracks) into the Playlist tab?\n\n'
                          f'The Playlist tab has {self.playlist_tree.topLevelItemCount()} track(s). '
                          'Replace them, or add the new ones after them?', parent=self)
        replace = box.addButton('Replace', QMessageBox.AcceptRole)
        add = box.addButton('Add after', QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.exec_()
        clicked = box.clickedButton()
        return 'replace' if clicked is replace else 'add' if clicked is add else None

    # -- saving ----------------------------------------------------------------

    def _ask_name(self, title, default='', parent=None):
        name, ok = QInputDialog.getText(parent or self, title, 'Name:', QLineEdit.Normal, default)
        return name.strip() if ok and name.strip() else None

    def _free_name(self, name, parent=None, replace_kind=None, keep=None):
        """True if `name` can be used: unused (or `keep`, the list being renamed), or a list of
        `replace_kind` the user agrees to replace."""
        existing = self.library_store.saved_list(name)
        if existing is None or (keep and existing['name'].casefold() == keep.casefold()):
            return True
        what = 'smartlist' if existing['kind'] == SMARTLIST else 'playlist'
        if existing['kind'] != replace_kind:
            QMessageBox.warning(parent or self, 'Name in use', f'There is already a {what} called "{existing["name"]}".')
            return False
        return QMessageBox.question(parent or self, f'Replace {what}', f'Replace the {what} "{existing["name"]}"?',
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def _saved(self, action, *args):
        """Run a library_store change; returns an error message, or '' on success."""
        try:
            action(*args)
        except sqlite3.Error as error:
            message = f'Could not save: {error}'
            self._report(message, 'error')
            return message
        self.refresh_saved_lists()
        return ''

    def _after_change(self, node):
        """A saved list changed: refresh the List view if it shows that list."""
        source = self.list_source
        if source and source['kind'] == node['kind'] and source['name'].casefold() == node['name'].casefold():
            self.show_list_source(node)

    def save_playlist_as(self, name=None):
        """Save the Playlist tab as a playlist under Playlists in the Browser."""
        name = name or self._ask_name('Save the Playlist tab as a playlist')
        if not name or not self._free_name(name, replace_kind=PLAYLIST):
            return None
        records = self._playlist_records()
        if self._saved(self.library_store.save_playlist, name, records):
            return None
        node = {'kind': PLAYLIST, 'name': name}
        self._after_change(node)
        self._report(f'Saved playlist "{name}" ({len(records)} tracks)')
        return node

    def replace_playlist(self, node):
        records = self._playlist_records()
        if QMessageBox.question(self, 'Replace playlist',
                                f'Replace "{node["name"]}" with the {len(records)} track(s) of the Playlist tab?',
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if not self._saved(self.library_store.save_playlist, node['name'], records):
            self._after_change(node)
            self._report(f'Saved playlist "{node["name"]}" ({len(records)} tracks)')

    def new_playlist(self):
        name = self._ask_name('New playlist')
        if name and self._free_name(name) and not self._saved(self.library_store.save_playlist, name, []):
            self._report(f'Created playlist "{name}"; drag tracks onto it')

    def save_smartlist(self, name, rules):
        if self._saved(self.library_store.save_smartlist, name, rules):
            return None
        node = {'kind': SMARTLIST, 'name': name}
        self._after_change(node)
        self._report(f'Saved smartlist "{name}"')
        return node

    def save_smartlist_from_search(self, rules):
        """Save as Smartlist in the Complex Search dialog."""
        parent = self.advanced_search_dialog
        name = self._ask_name('Save as Smartlist', parent=parent)
        if name and self._free_name(name, parent, replace_kind=SMARTLIST):
            self.save_smartlist(name, rules)

    def _smartlist_dialog(self, name, rules):
        dialog = AdvancedSearchDialog(FIELD_LABELS, self, smartlist=name)
        dialog.set_filters(rules)
        return dialog.saved_filters() if dialog.exec_() == QDialog.Accepted else None

    def new_smartlist(self):
        """Name it, then set its rules (starting from the current Complex Search)."""
        name = self._ask_name('New smartlist')
        if not name or not self._free_name(name):
            return
        rules = self._smartlist_dialog(name, self.current_advanced_search.get('filters', []))
        if rules is not None and self.save_smartlist(name, rules):
            self.show_list_source({'kind': SMARTLIST, 'name': name})

    def edit_smartlist(self, node):
        saved = self.library_store.saved_list(node['name'])
        rules = self._smartlist_dialog(node['name'], saved['rules'] or []) if saved else None
        if rules is not None:
            self.save_smartlist(node['name'], rules)

    def rename_saved_list(self, node):
        name = self._ask_name(f'Rename {node["kind"]}', node['name'])
        if not name or name == node['name'] or not self._free_name(name, keep=node['name']):
            return
        if self._saved(self.library_store.rename_saved_list, node['name'], name):
            return
        source = self.list_source
        if source and source['kind'] == node['kind'] and source['name'].casefold() == node['name'].casefold():
            self.show_list_source({'kind': node['kind'], 'name': name})

    def duplicate_saved_list(self, node):
        name, number = f'{node["name"]} copy', 2
        while self.library_store.saved_list(name) is not None:
            name, number = f'{node["name"]} copy {number}', number + 1
        if node['kind'] == PLAYLIST:
            error = self._saved(self.library_store.save_playlist, name, self.library_store.load_playlist(node['name']))
        else:
            rules = (self.library_store.saved_list(node['name']) or {}).get('rules') or []
            error = self._saved(self.library_store.save_smartlist, name, rules)
        if not error:
            self._report(f'Created "{name}"')

    def delete_saved_list(self, node, confirm=True):
        if confirm and QMessageBox.question(
                self, f'Delete {node["kind"]}',
                f'Delete the {node["kind"]} "{node["name"]}"?\n\nThe tracks stay in the library; files are not touched.',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if self._saved(self.library_store.delete_saved_list, node['name']):
            return
        source = self.list_source
        if source and source['kind'] == node['kind'] and source['name'].casefold() == node['name'].casefold():
            self.show_list_source(None)
        self._report(f'Deleted {node["kind"]} "{node["name"]}"')

    def add_tracks_to_saved_playlist(self, node, mime):
        """Tracks dropped onto a playlist in the Browser, or onto the List while it shows that
        playlist, are added at its end, in the dropped order."""
        paths = dragged_tracks(mime)
        unreadable = 0
        if not paths:  # files from Explorer or Traktor: into the library first, keeping the List as it is
            files = list(dict.fromkeys(audio_paths(mime)))
            paths = [record['File_Path'] for record in self.import_audio_files(files, keep_view=True)]
            # Missing files never reach the import: count what was dropped (files, and files in folders)
            dropped = {canonical_path(os.path.normpath(url.toLocalFile())) for url in mime.urls()
                       if url.isLocalFile() and not os.path.isdir(url.toLocalFile())}
            unreadable = len(dropped | set(map(canonical_path, files))) - len(paths)
        rows = self._rows_by_path()
        records = [rows[key] for key in map(canonical_path, paths) if key in rows]
        try:
            added = self.library_store.add_to_playlist(node['name'], records)
        except sqlite3.Error as error:
            self._report(f'Could not save: {error}', 'error')
            return
        self._after_change(node)
        skipped = len(records) - added
        self._report(f'Added {added} track(s) to "{node["name"]}"' +
                     (f'; {skipped} already on it' if skipped else '') +
                     (f'; {unreadable} file(s) could not be read or are missing' if unreadable else ''),
                     'warning' if unreadable else 'ok')

    def _browser_menu(self, node, position):
        menu = QMenu(self)
        kind = node['kind'] if node else 'playlists'
        if kind in TRACK_SOURCES:
            menu.addAction('Show in List').triggered.connect(lambda: self.show_list_source(node))
            menu.addAction('Load into the Playlist tab').triggered.connect(lambda: self.load_into_playlist(node))
        if kind == TRAKTOR:
            missing = len(self._traktor_missing(node))
            action = menu.addAction(f'Import its {missing} missing track(s) into the library')
            action.setEnabled(bool(missing))
            action.triggered.connect(lambda: self.import_traktor_missing(node))
            menu.addAction('Copy to my playlists...').triggered.connect(lambda: self.copy_traktor_playlist(node))
        if kind == PLAYLIST:
            menu.addAction('Replace with the Playlist tab...').triggered.connect(lambda: self.replace_playlist(node))
        if kind == SMARTLIST:
            menu.addAction('Edit rules...').triggered.connect(lambda: self.edit_smartlist(node))
        if kind in SAVED_KINDS:
            menu.addSeparator()
            menu.addAction('Rename...').triggered.connect(lambda: self.rename_saved_list(node))
            menu.addAction('Duplicate').triggered.connect(lambda: self.duplicate_saved_list(node))
            menu.addAction('Delete...').triggered.connect(lambda: self.delete_saved_list(node))
        if kind in SAVED_KINDS or kind == 'playlists':
            menu.addSeparator()
            menu.addAction('New playlist...').triggered.connect(self.new_playlist)
            menu.addAction('New smartlist...').triggered.connect(self.new_smartlist)
            menu.addAction('Save the Playlist tab as...').triggered.connect(lambda: self.save_playlist_as())
        if not menu.isEmpty():
            menu.exec_(position)

# Rekordbox

SongSelector reads Rekordbox's own library, `master.db`, directly. Nothing has to be exported, and Rekordbox can be
running or closed. The app reads from a temporary copy, so it **never writes to Rekordbox's library**.

## Finding the library

At start-up the app takes the location from Rekordbox's own settings, otherwise
`%APPDATA%\Pioneer\rekordbox\master.db`.

Somewhere else? **Import → Link Rekordbox library…** and pick the `master.db`.

## What comes in

- **Playlists**, with Rekordbox's folders and order, under **Rekordbox Playlists** in the Browser tab. They work
  like [Traktor's playlists](traktor.md#using-traktors-playlists): click to show, double-click to load,
  right-click to import missing tracks or make an editable copy.
- Rekordbox **smartlists** are listed but not evaluated yet.
- Rekordbox's own key, BPM, colours and ratings are **not read yet**; the file tags are used for those.

## Keeping up to date

The library is read again whenever Rekordbox saves. If a future Rekordbox version changes its format and the
library cannot be read, the Browser keeps the last playlists it had and the status bar says why.

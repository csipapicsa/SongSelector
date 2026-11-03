# Importing Rekordbox playlists into SongSelector

Checked 2026-11-03 on the development machine. Nothing is built yet; this is the feasibility and the plan.
Compare what was done for Traktor's playlists in 4.23.0 (read-only entries in the Browser, "import its missing
tracks", "copy to my playlists").

## What is installed and where the data is

- Installed: rekordbox 6.8.5, 7.1.1, 7.2.6 and 7.2.19 (uninstall entries; `C:\Program Files\Pioneer\rekordbox 6.8.5`).
- Library: `%APPDATA%\Pioneer\rekordbox\master.db` (20 MB, last written 2026-10-30), with `master.backup*.db` next to it.
  Settings and analysis are in `%APPDATA%\Pioneer\rekordbox6\`. Rekordbox was not running.
- No `rekordbox.xml` export exists on disk. `Documents\rekordbox\` holds only an import log from 2024-02-29.

## Two ways in

| | A. XML export | B. Read `master.db` directly |
|---|---|---|
| How | In Rekordbox: File menu > *Export Collection in xml format* (menu name to confirm in 7.x), then the app reads the file | `master.db` is encrypted (SQLCipher). The open-source [pyrekordbox](https://github.com/dylanljones/pyrekordbox) opens it with a key that it is documented to find on the machine |
| Dependency | None: the file is plain XML ([format](https://pyrekordbox.readthedocs.io/en/stable/formats/xml.html)); Python's `xml` is enough | `pyrekordbox` + `sqlcipher3-wheels` (binary) + SQLAlchemy; they would have to go into the exe |
| Fresh data | Only as fresh as the last export, by hand | Always current; Rekordbox locks the file while it runs, so read a copy |
| Risk | Low: a documented exchange format | Medium: unofficial, the key and schema change with Rekordbox versions (pyrekordbox renamed its main class in 0.5.0 and warns it will remove the old name) |
| Content | Tracks (BPM, key, rating, colour, comment, location), playlists in order, cues | Same, plus play counts etc. |

**Tested B on a copy of the database** (pyrekordbox 0.5.0 in a throw-away environment; the copy is deleted):
it opened without asking for a key. Contents:

| | |
|---|---|
| Tracks | 4,166 (564 with a rating) |
| Playlists | 5, no folders, no smart playlists: "Demo" 41 tracks, "Untitled Playlist" 2, "2024" 2,229, "CUE Analysis Playlist" 0, "MT / kez detection" 603 |
| Overlap with the SongSelector library (3,734 tracks) | 949 tracks; **none of the playlist tracks** are in it yet |

So an import would first have to bring in the missing files (as with Traktor's playlists), and Rekordbox's
fields (rating 0-5, colour, key) would map onto the app's columns.

## Recommendation

1. Build **A** first: a `RekordboxCollection` reader like `TraktorCollection`, a Browser root *Rekordbox Playlists*,
   *Import its missing tracks*, *Copy to my playlists*. The user exports the XML when wanted; the app watches the file.
2. Add **B** later as an option ("read Rekordbox directly") if the manual export is a nuisance, and only as an
   optional download so the exe does not carry SQLCipher.
3. Open question for the user: which one matters (the three playlists "2024", "MT / kez detection", "Demo" look
   like analysis/test material, not performance playlists).

Effort: about the same as the Traktor playlists work (parser, Browser root, menu, tests), plus a path mapping:
Rekordbox stores locations as `file://localhost/E:/DJ/a.mp3` (XML) or `E:/DJ/a.mp3` (database).

# Mixxx

SongSelector reads Mixxx's library, `mixxxdb.sqlite`, directly. Mixxx may stay open; **nothing is written to it**.
Works on Windows and Linux.

## Finding the library

Found by itself in the usual places:

| System | Location |
|---|---|
| Linux | `~/.mixxx` |
| Linux, Flathub | `~/.var/app/org.mixxx.Mixxx/.mixxx` |
| Windows | `%LOCALAPPDATA%\Mixxx` |

Somewhere else? **Import → Link Mixxx library…**

## What comes in

- **Key, BPM, rating and colour** when the file's own tags do not have them.
- **Exact colours:** a Mixxx colour is shown as Mixxx shows it. Colour searches find it by its family:
  `color:orange` finds Mixxx's `#FF8800`.
- **Playlists, crates and history** under **Mixxx Playlists** in the Browser tab.

## Keeping up to date

Changes made in Mixxx come in after Mixxx saves them.

If you also use Traktor, see [Primary DJ program](index.md#if-more-than-one-program-knows-a-track).

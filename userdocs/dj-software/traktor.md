# Traktor

SongSelector reads Traktor's collection file, `collection.nml`. It **never writes to it**.

## Finding the collection

At start-up the app looks under `Documents\Native Instruments\Traktor*\` and uses the collection it finds there.

If you keep Traktor's files somewhere else, or have several Traktor versions installed:
**Import → Link Traktor collection…** and pick the `collection.nml` you use.

## What comes in

- **Key, BPM, colour and rating** for every track you have added to SongSelector.
- **Playlists**, with Traktor's folders and order, under **Traktor Playlists** in the Browser tab.
- **Smartlists**, evaluated on Traktor's own data (BPM, colour, rating, genre, key, length, play count, import
  date…), so they show the same tracks as in Traktor.

## Keeping up to date

Traktor writes `collection.nml` when it saves, which is mostly **when Traktor closes**. SongSelector notices and
reads it again in the background; the status bar then says what changed, for example
*Updated from Traktor: 12 tracks (BPM 3, colour 8, rating 2)*. Changes made while SongSelector was closed come in a
few seconds after it starts.

## Using Traktor's playlists

| Action | Result |
|---|---|
| Click a playlist (or drag it onto the List) | The List shows its tracks, in Traktor's order (`#` column) |
| Double-click it (or drag it onto the Playlist tab) | Loads it into the Playlist tab |
| Right-click → *Import its missing tracks into the library* | Adds the playlist's tracks you have not added yet |
| Right-click → *Copy to my playlists…* | An editable copy under your own playlists |

## Back into Traktor

Drag tracks from the List, the map or the search results straight **onto a Traktor deck or playlist**.

!!! note "Smartlist limits"
    Traktor does not store two details of its smartlist rules, so SongSelector assumes them: `~` means within
    1 BPM, and `&` binds tighter than `|`. A smartlist on *played in this session* cannot be evaluated outside
    Traktor; the bar above the List says so.

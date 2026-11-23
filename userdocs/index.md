# SongSelector

**Pick the next track.** SongSelector is a desktop app for Windows and Linux that sits next to Traktor, Rekordbox
or Mixxx and helps you decide what to play next. It reads your DJ software's library by itself: nothing to export,
nothing to keep in sync by hand.

<!-- screenshot: main window, List with keys at master tempo + similarity map tab -->

It answers three questions:

<div class="grid cards" markdown>

- **Will it mix in key at the tempo I'm playing?**

    With Key Lock off, speeding a track up raises its pitch. SongSelector shows every track's key *at the current
    master tempo* and recalculates the whole library when you change it.
    [Keys at the master tempo](using/key-and-tempo.md)

- **What sounds like this track?**

    Audio models listen to every track in the background. A map and a closest-matches list then show tracks that
    *sound* alike, whatever their tags say.
    [Similarity map](sound/similarity-map.md)

- **Which of my tracks sound like *this*?**

    Type a description, *"funky breakbeat with a groovy bassline"*, and get the closest tracks in your library.
    [Search by description](sound/describe.md)

</div>

## Start here

1. [Install](getting-started/install.md) the app (Windows exe or Linux AppImage, no Python needed).
2. [First start](getting-started/first-start.md): add your music and see your keys.
3. [Connect your DJ software](dj-software/index.md) so key, BPM, colours, ratings and playlists come in by themselves.
4. Optional: [get the models](sound/models.md) for the sound-based features.

Something not working? See [Troubleshooting](troubleshooting.md).

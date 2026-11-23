# Troubleshooting

??? question "Windows says *Windows protected your PC*"
    The exe is not code-signed yet. Click **More info → Run anyway**. See [Install](getting-started/install.md).

??? question "My Traktor / Rekordbox / Mixxx library is not found"
    Link it by hand from the **Import** menu: *Link Traktor collection…*, *Link Rekordbox library…* or
    *Link Mixxx library…*. See [Connect your DJ software](dj-software/index.md) for where each program keeps it.

??? question "A change I made in Traktor does not show up"
    Traktor writes its collection mostly when it **closes**. Save or close Traktor; SongSelector reads it again by
    itself within a few seconds.

??? question "My library is empty"
    A fresh install starts empty. Add your music with **Import → Add folder (with subfolders)…** or by dragging
    files onto the window. See [First start](getting-started/first-start.md).

??? question "The map or search by description shows nothing"
    These need a model and analysed tracks. Check **Analysis → Embedding models** for how many tracks are done,
    and that *Analyse embeddings in background* is on. See [Getting the models](sound/models.md).

??? question "Analysis is slow"
    Check the status bar: *CPU* is several times slower than *GPU (DirectML)*. Analysis runs at low priority on
    purpose, so it slows down while you use the computer. It only has to happen once per track.

??? question "Where are my settings and library? How do I back up?"
    In one folder: next to the exe on Windows, `~/.local/share/SongSelector` on Linux. Back up `library.sqlite`
    and `SongSelector_settings.json`. See [Where your data lives](getting-started/install.md#where-your-data-lives).

## Still stuck?

Open an issue on [GitHub](https://github.com/csipapicsa/SongSelector/issues) with your SongSelector version, your
Windows or Linux version, and what you did.

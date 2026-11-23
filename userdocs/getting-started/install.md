# Install

Download the app from the [latest release](https://github.com/csipapicsa/SongSelector/releases/latest). Both
downloads are self-contained: no Python or anything else to install.

=== "Windows"

    1. Download `SongSelector-<version>.exe`.
    2. Put it in **its own folder**, for example `Documents\SongSelector\`. The app keeps its settings and library
       next to the exe, so a folder of its own keeps things tidy.
    3. Double-click it.

    !!! warning "Windows protected your PC"
        The exe is not code-signed yet, so SmartScreen warns the first time. Click **More info → Run anyway**.
        To check that the download is genuine, compare its SHA-256 with `SHA256SUMS.txt` from the same release:
        `Get-FileHash .\SongSelector-*.exe` in PowerShell.

=== "Linux"

    1. Download `SongSelector-<version>-x86_64.AppImage`.
    2. Make it executable and start it:

        ```bash
        chmod +x SongSelector-*-x86_64.AppImage
        ./SongSelector-*-x86_64.AppImage
        ```

    Runs on distributions from about 2022 on (built on Ubuntu 22.04). If it complains about FUSE, start it with
    `--appimage-extract-and-run`. On Linux the app works with Mixxx (also the Flathub version); Traktor and Rekordbox
    do not run there. Audio analysis runs on the CPU.

## Where your data lives

Everything the app keeps is in one folder:

- **Windows:** next to the exe.
- **Linux:** `~/.local/share/SongSelector`.

| File | What it is | Safe to delete? |
|---|---|---|
| `SongSelector_settings.json` | Columns, search settings, tempo, colouring | Resets your settings |
| `library.sqlite` | Every track you added, your playlists and smartlists | **No**: back it up |
| `embeddings*.sqlite` | What the audio models learned about each track | Yes, rebuilt in the background (takes a while) |
| `models\` | The downloaded audio models | Yes, *Get models…* downloads them again |

!!! tip "Back up before upgrading"
    Copy `library.sqlite` and `SongSelector_settings.json` somewhere safe before you upgrade.

## Upgrading

Put the new exe in the **same folder** as the old one and start it (Linux: replace the AppImage). Your library,
playlists and settings are picked up. You can delete the old exe afterwards.

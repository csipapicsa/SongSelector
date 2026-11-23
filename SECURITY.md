# Security and safety

SongSelector is a free, open-source (GPL-3.0) desktop app. Every line of it is in this repository, and every
release is built from it by GitHub Actions. This page says what the app does on your computer and how you can check
a download yourself, so you don't have to take anyone's word for it.

## What the app does and doesn't do

Each statement points to the code that backs it.

| | |
|---|---|
| **Network** | Only one thing goes online: **model downloads from Hugging Face**, and only when you press *Download* in *Analysis → Get models…*. Files come from fixed versions and are used only after their SHA-256 matches the list in the app ([core/model_download.py](src/songselector/core/model_download.py), the app's only network code). No telemetry, no analytics, no update check, no account, nothing uploaded. |
| **Your DJ software** | Traktor's `collection.nml`, Mixxx's `mixxxdb.sqlite` and Rekordbox's `master.db` are **read, never written**. Rekordbox's database is read from a temporary copy ([core/traktor_collection.py](src/songselector/core/traktor_collection.py), [core/mixxx_library.py](src/songselector/core/mixxx_library.py), [core/rekordbox_library.py](src/songselector/core/rekordbox_library.py)). |
| **Your music files** | Read to show tags and to analyse the sound. A file is changed only when **you** edit its Artist / Title / Genre / Comment in the app. Removing tracks or deleting duplicates removes list rows, **never files on disk**. |
| **What it writes** | Its own folder only: settings, its library database, analysis caches and downloaded models (on Windows next to the exe, on Linux `~/.local/share/SongSelector`). |
| **Permissions** | Needs **no administrator rights** and installs nothing: no services, no drivers, no registry changes, no startup entries. Delete the folder and it's gone. |
| **Background work** | Audio analysis runs in a separate process at low CPU and disk priority, on the GPU (DirectML) or the CPU. |

## Verifying a download

Every [release](https://github.com/csipapicsa/SongSelector/releases) is built and published by the
[release workflow](.github/workflows/release.yml) from a version tag. Nothing is uploaded by hand.

1. **Checksum.** Compare the file's SHA-256 with `SHA256SUMS.txt` from the same release.
   Windows PowerShell: `Get-FileHash .\SongSelector-<version>.exe`. Linux: `sha256sum SongSelector-*.AppImage`.
2. **Build provenance.** Each release file has a signed attestation from GitHub stating that this exact file was
   built by this repository's release workflow from the tagged commit
   ([Attestations](https://github.com/csipapicsa/SongSelector/attestations)). Check it with the
   [GitHub CLI](https://cli.github.com/):

   ```
   gh attestation verify SongSelector-<version>.exe --repo csipapicsa/SongSelector
   ```

   (Attestations exist for releases published after 2026-11-23.)
3. **Antivirus scan.** Release notes link each file's [VirusTotal](https://www.virustotal.com/) report, made when
   it was published.
4. **The source.** Before a release is built, CI runs the tests on Windows and Linux, a dependency audit
   (`pip-audit`) and a secret scan (`gitleaks`); the release build then checks itself inside the packaged app
   ([ci.yml](.github/workflows/ci.yml), [selfcheck.py](src/songselector/selfcheck.py)).

## Windows warnings

The exe is **not code-signed** (signing costs money every year; this is a free hobby project). What that means:

- **Expected:** a blue *Windows protected your PC* screen from SmartScreen on first start. Click
  **More info → Run anyway**. This appears for most unsigned apps that few people have downloaded yet.
- **Not expected:** no administrator (UAC) prompt, because the app doesn't ask for admin rights.
- **Not expected:** a **red** antivirus alert saying the file is a threat. Apps packaged with PyInstaller are sometimes
  misjudged by heuristics. If it happens, check the VirusTotal link and the checksum, and please
  [open an issue](https://github.com/csipapicsa/SongSelector/issues) so it can be reported as a false positive.
- **Smart App Control** (some Windows 11 PCs) can block unsigned apps completely, with no *Run anyway*. That's a
  Windows setting, not a detection.

## Reporting a security problem

Please report vulnerabilities privately: **Security → Report a vulnerability** on this repository
([private vulnerability reporting](https://github.com/csipapicsa/SongSelector/security/advisories/new)).
Don't open a public issue for a security problem. Other bugs: [issues](https://github.com/csipapicsa/SongSelector/issues).

Only the latest release gets fixes.

## The audio models

The optional models are published research models (PANNs, LAION, Microsoft, MTG), converted to ONNX: a data format
for neural network weights, run by Microsoft's onnxruntime, not executable code. Each one's source, changes and
licence are on its Hugging Face page, linked from [the user guide](https://csipapicsa.github.io/SongSelector/sound/models/).

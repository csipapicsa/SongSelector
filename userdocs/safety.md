# Is it safe?

Short answer: SongSelector is **open source**. Everything it does is in its
[public code](https://github.com/csipapicsa/SongSelector), and every download is built from that code by GitHub, not
on someone's PC. You don't have to trust anyone: below is how to check it yourself.

## What it does on your computer

- **Goes online for one thing only:** downloading the optional audio models from Hugging Face, when you press
  *Download*. No tracking, no analytics, no account, no update check. Nothing about you or your music is sent anywhere.
- **Never writes to your DJ software.** Traktor, Rekordbox and Mixxx libraries are only read.
- **Never deletes your music.** It changes a file only when you edit its tags (artist, title, genre, comment) in the
  app. Removing tracks or deleting duplicates removes them from the list, not from your disk.
- **Needs no admin rights and installs nothing.** Its files stay in its own folder; delete the folder and it's gone.

## The Windows warning

SongSelector isn't code-signed: a signing certificate costs money every year, and this is a free project.

<div class="grid cards" markdown>

- :material-shield-alert-outline:{ .lg } **Blue: "Windows protected your PC"**

    Expected the first time. Click **More info → Run anyway**. Windows shows this for most unsigned apps that few
    people have downloaded.

- :material-alert-octagon-outline:{ .lg } **Red: "Threat found"**

    Not expected. Antivirus heuristics sometimes misjudge apps packaged like this one (PyInstaller). Check the
    download as below, and please [tell us](https://github.com/csipapicsa/SongSelector/issues) so it can be reported as
    a false positive.

</div>

You won't see an administrator (UAC) prompt: the app doesn't ask for admin rights. On some Windows 11 PCs,
**Smart App Control** blocks unsigned apps completely; that's a Windows setting, not a detection.

## Check your download

Each [release](https://github.com/csipapicsa/SongSelector/releases) has three ways to check it:

1. **Checksum:** the file's fingerprint must match `SHA256SUMS.txt` from the same release.
   In PowerShell: `Get-FileHash .\SongSelector-<version>.exe`.
2. **Antivirus scan:** the release notes link each file's [VirusTotal](https://www.virustotal.com/) report, where
   about 70 antivirus engines checked it.
3. **Built from the public code:** GitHub signs a record that the file was built from this repository by its release
   workflow. With the [GitHub CLI](https://cli.github.com/):
   `gh attestation verify SongSelector-<version>.exe --repo csipapicsa/SongSelector`

!!! tip "Asking an AI assistant?"
    Point it at the repository and its [SECURITY.md](https://github.com/csipapicsa/SongSelector/blob/main/SECURITY.md),
    which lists each claim above with the code behind it.

## Found a security problem?

Please report it privately: on GitHub, **Security → Report a vulnerability**
([direct link](https://github.com/csipapicsa/SongSelector/security/advisories/new)).

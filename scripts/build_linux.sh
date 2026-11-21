#!/usr/bin/env bash
# Builds the Linux AppImage: dist/SongSelector-<version>-x86_64.AppImage (the Linux counterpart of build.ps1).
#
#   scripts/build_linux.sh
#
# Needs the virtual environment (python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt) and
# curl. PyInstaller builds one folder (packaging/SongSelector.spec); appimagetool packs it with the AppImage runtime
# into one file that mounts itself when started. Build on the oldest system the AppImage should run on (CI:
# ubuntu-22.04): the bundled libraries need at least that system's glibc.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python="$root/.venv/bin/python"
[ -x "$python" ] || { echo "Virtual environment not found ($root/.venv): see the comment at the top." >&2; exit 1; }
version="$(sed -n "s/^__version__ = '\(.*\)'$/\1/p" "$root/src/songselector/__init__.py")"
[ -n "$version" ] || { echo "No __version__ in src/songselector/__init__.py" >&2; exit 1; }

# Intermediate files (hundreds of MB) go to the temp folder; only the AppImage lands in dist/.
work="${TMPDIR:-/tmp}/songselector-build"
tools="$work/tools"
mkdir -p "$tools" "$root/dist"

# appimagetool and the AppImage runtime: fixed releases, checked against their SHA-256 (GitHub's digests of the
# assets). Their "continuous" builds would change under us. The type 2 runtime is static: the AppImage needs no
# libfuse2 on the user's system, only FUSE itself (or --appimage-extract-and-run).
APPIMAGETOOL_URL='https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage'
APPIMAGETOOL_SHA256='ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0'
RUNTIME_URL='https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64'
RUNTIME_SHA256='2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d'

fetch() {  # url sha256 file: download unless a file with that checksum is already there
  local url="$1" sum="$2" file="$3"
  if [ -f "$file" ] && echo "$sum  $file" | sha256sum --check --status; then
    return
  fi
  curl -sSfL --retry 3 -o "$file.part" "$url"
  if ! echo "$sum  $file.part" | sha256sum --check --status; then
    rm -f "$file.part"
    echo "Checksum mismatch: $url" >&2
    exit 1
  fi
  mv "$file.part" "$file"
}
fetch "$APPIMAGETOOL_URL" "$APPIMAGETOOL_SHA256" "$tools/appimagetool"
fetch "$RUNTIME_URL" "$RUNTIME_SHA256" "$tools/runtime-x86_64"
chmod +x "$tools/appimagetool"

export PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0
export PYINSTALLER_CONFIG_DIR="$work/pyinstaller-cache"
"$python" -B -m PyInstaller --noconfirm --clean --distpath "$work/dist" --workpath "$work/build" \
  "$root/packaging/SongSelector.spec"

# The AppDir: the one-folder build under usr/lib, a desktop entry and the icon at the top (appimagetool takes the
# name and icon from there), and AppRun, which the runtime starts.
appdir="$work/SongSelector.AppDir"
rm -rf "$appdir"
mkdir -p "$appdir/usr/lib" "$appdir/usr/share/applications" "$appdir/usr/share/icons/hicolor/256x256/apps"
cp -a "$work/dist/SongSelector" "$appdir/usr/lib/songselector"
cp "$root/packaging/linux/songselector.desktop" "$appdir/songselector.desktop"
cp "$root/packaging/linux/songselector.desktop" "$appdir/usr/share/applications/"
cp "$root/src/songselector/ui/icon.png" "$appdir/songselector.png"
cp "$root/src/songselector/ui/icon.png" "$appdir/usr/share/icons/hicolor/256x256/apps/songselector.png"
ln -s songselector.png "$appdir/.DirIcon"
cat > "$appdir/AppRun" <<'APPRUN'
#!/bin/sh
# Started by the AppImage runtime from the mounted image ($APPDIR).
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/songselector/songselector" "$@"
APPRUN
chmod +x "$appdir/AppRun"

out="$root/dist/SongSelector-$version-x86_64.AppImage"
rm -f "$out"
# appimagetool is an AppImage itself: extract-and-run, so building needs no FUSE (containers, CI).
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$tools/appimagetool" --no-appstream \
  --runtime-file "$tools/runtime-x86_64" "$appdir" "$out"

echo
echo "Built:  $out"
echo "Size:   $(du -m "$out" | cut -f1) MB"
echo "SHA256: $(sha256sum "$out" | cut -d' ' -f1)"

#!/usr/bin/env bash
# Uploads files to VirusTotal (API v3) and prints one Markdown line per file, linking its report.
#   VT_API_KEY=... scripts/virustotal_scan.sh release/SongSelector-* > links.md
# Every file goes through a one-time upload URL, which takes files over 32 MB (the exe is ~120 MB).
set -euo pipefail
: "${VT_API_KEY:?VT_API_KEY is not set}"
for file in "$@"; do
  upload=$(curl -sSf -H "x-apikey: $VT_API_KEY" https://www.virustotal.com/api/v3/files/upload_url | jq -r .data)
  analysis=$(curl -sSf -H "x-apikey: $VT_API_KEY" -F "file=@$file" "$upload" | jq -r .data.id)
  sum=$(sha256sum "$file" | cut -d' ' -f1)
  echo "Uploaded $(basename "$file"), analysis $analysis" >&2
  echo "- [$(basename "$file")](https://www.virustotal.com/gui/file/$sum)"
done

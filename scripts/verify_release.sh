#!/usr/bin/env bash
# Verifies a built AppImage in two stages (the Linux counterpart of verify_release.ps1):
#   1. Packaged self-check: runs the AppImage headless with SONGSELECTOR_VERIFY_BUILD=1, which executes
#      songselector.selfcheck inside the frozen app.
#   2. Native smoke test: starts it normally on the X display, waits for its real window, closes it like the close
#      button would (WM_DELETE_WINDOW) and expects exit code 0 and the settings saved.
# Both stages use a throwaway data folder, so your real settings and tracks are never touched.
#
#   xvfb-run -a scripts/verify_release.sh [path/to/SongSelector-x.y.z-x86_64.AppImage]
#
# Without an X display (DISPLAY unset) only stage 1 runs. Optional, as in verify_release.ps1:
# SONGSELECTOR_VERIFY_MODEL=/path/cnn14.onnx and SONGSELECTOR_VERIFY_CLAP_MODELS=/folder/with/clap-*.onnx run a real
# analysis (and text query) inside the AppImage; SONGSELECTOR_VERIFY_DOWNLOAD=1 fetches the tokenizers.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
app="${1:-$(ls -t "$root"/dist/SongSelector-*-x86_64.AppImage 2>/dev/null | head -n 1)}"
[ -n "$app" ] && [ -f "$app" ] || { echo 'No AppImage in dist/. Run scripts/build_linux.sh first.' >&2; exit 1; }
app="$(readlink -f "$app")"
chmod +x "$app"
run_dir="${TMPDIR:-/tmp}/songselector-verify/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$run_dir/packaged" "$run_dir/native"
echo "Verifying $app"
echo "Results in $run_dir"

# A clean environment, so the app cannot use a local Python or Qt by accident.
clean_env=(env -i "HOME=$HOME" "PATH=/usr/bin:/bin" "LANG=${LANG:-C.UTF-8}" "SONGSELECTOR_EMBEDDING_MODEL=none")
# The AppImage mounts itself with FUSE; where there is none (containers), it can extract itself instead. Set only
# then: the runtime extracts whenever the variable exists, even empty.
if [ ! -e /dev/fuse ] || ! { command -v fusermount3 || command -v fusermount; } >/dev/null; then
  echo 'No FUSE here: the AppImage extracts itself instead of mounting.'
  clean_env+=("APPIMAGE_EXTRACT_AND_RUN=1")
fi

# ---- Stage 1: packaged self-check -------------------------------------------
result="$run_dir/packaged-results.json"
status=0
timeout 300 "${clean_env[@]}" "TMPDIR=$run_dir/packaged" "QT_QPA_PLATFORM=offscreen" \
  "SONGSELECTOR_APP_DATA_DIR=$run_dir/packaged" "SONGSELECTOR_VERIFY_BUILD=1" "SONGSELECTOR_VERIFY_RESULT=$result" \
  "SONGSELECTOR_VERIFY_MODEL=${SONGSELECTOR_VERIFY_MODEL:-}" \
  "SONGSELECTOR_VERIFY_CLAP_MODELS=${SONGSELECTOR_VERIFY_CLAP_MODELS:-}" \
  "SONGSELECTOR_VERIFY_DOWNLOAD=${SONGSELECTOR_VERIFY_DOWNLOAD:-}" \
  "$app" || status=$?
[ -f "$result" ] && cat "$result"
[ "$status" -eq 0 ] || { echo "Packaged self-check failed (exit code $status)." >&2; exit 1; }
python3 -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1]))["ok"] else 1)' "$result" \
  || { echo 'Packaged self-check reported failure.' >&2; exit 1; }

# ---- Stage 2: native window smoke test ----------------------------------
if [ -z "${DISPLAY:-}" ]; then
  echo 'No X display: the window test is skipped (run under xvfb-run -a for it).'
  exit 0
fi
native="$run_dir/native"
"${clean_env[@]}" "DISPLAY=$DISPLAY" "XAUTHORITY=${XAUTHORITY:-}" "TMPDIR=$native" "QT_QPA_PLATFORM=xcb" \
  "SONGSELECTOR_APP_DATA_DIR=$native" "$app" > "$native/output.log" 2>&1 &
pid=$!
stop() { kill "$pid" 2>/dev/null || true; }
trap stop EXIT
# The main window, "SongSelector <version>" (not the startup splash). 60 s: a cold start on a busy runner.
if ! window="$(python3 "$root/scripts/x11_window.py" wait 'SongSelector ' 60)"; then
  cat "$native/output.log" >&2
  kill -0 "$pid" 2>/dev/null && echo 'App window was not found.' >&2 || echo 'App exited before opening its window.' >&2
  exit 1
fi
sleep 2
python3 "$root/scripts/x11_window.py" close "$window"
code=0
for _ in $(seq 100); do  # 10 s to close
  kill -0 "$pid" 2>/dev/null || break
  sleep 0.1
done
if kill -0 "$pid" 2>/dev/null; then
  echo 'App did not close cleanly.' >&2
  exit 1
fi
wait "$pid" || code=$?
trap - EXIT
[ "$code" -eq 0 ] || { cat "$native/output.log" >&2; echo "App exited with code $code." >&2; exit 1; }
python3 -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1])).get("Rating display version") == 1 else 1)' \
  "$native/SongSelector_settings.json" || { echo 'Settings were not saved on close.' >&2; exit 1; }
printf '{"ok": true, "executable": "%s", "window_found": true, "closed_cleanly": true, "exit_code": 0, "settings_saved": true}\n' \
  "$app" | tee "$run_dir/native-results.json"
echo
echo 'Release verification passed.'

#!/bin/bash
# Start the web UI + API against a fake mpv: no HDMI, no sound, no Init7 network needed (the channel list is fetched from Init7's public API).
# Open http://localhost:8099 (the devcontainer forwards the port). Playing a channel only "plays" in the mock.
# Live reload: the open page reloads itself when ui.html, the logo or the translations change (TV7_DEV_RELOAD), and control.py
# and the mock are restarted when their code or the texts (i18n/*.json) change. Stop with Ctrl+C.
set -eu
cd "$(dirname "$0")/.."
RUN=${TMPDIR:-/tmp}/tv7-dev; mkdir -p "$RUN/data"
[ -s "$RUN/data/options.json" ] || echo '{}' > "$RUN/data/options.json"
WATCH=(tv7_player/rootfs/control.py tv7_player/rootfs/tv7/*.py tv7_player/tests/mock_mpv.py tv7_player/rootfs/i18n/*.json)
MOCK=""; CTRL=""

start() {
  python3 tv7_player/tests/mock_mpv.py "$RUN/mpv.sock" & MOCK=$!
  sleep 0.5
  TV7_UI_PORT=8099 TV7_UI_BIND=0.0.0.0 TV7_UI_ALLOW="0.0.0.0/0,::/0" TV7_OPTIONS="$RUN/data/options.json" \
  TV7_FAVORITES="$RUN/data/favorites.json" TV7_LOGO_DIR="$RUN/data/logos" \
  TV7_DRM_DIR="$RUN/drm" TV7_TRANSLATIONS="$PWD/tv7_player/translations" TV7_VERSION=dev TV7_DEV_RELOAD=1 \
    python3 tv7_player/rootfs/control.py "$RUN/mpv.sock" 8765 & CTRL=$!
}
stop() {
  kill "$CTRL" "$MOCK" 2>/dev/null || true
  wait "$CTRL" "$MOCK" 2>/dev/null || true
}
stamp() { stat -c %Y "${WATCH[@]}" 2>/dev/null | sort -n | tail -1; }

trap 'stop; exit 0' INT TERM
trap stop EXIT
start
last=$(stamp)
echo ">>> http://localhost:8099 (live reload on)"
while sleep 1; do
  now=$(stamp)
  if [ "$now" != "$last" ]; then
    last=$now
    echo ">>> code changed: restarting control.py and the mock"
    stop; start
  fi
done

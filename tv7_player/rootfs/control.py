"""TV7 Player: small HTTP API for mpv, exclusively for Init7 TV7 channels. This file is the start; the code is in the package tv7/
(one module per topic, see docs/DEVELOPMENT.md).

Endpoints (GET):
  /health                          liveness check (no token needed)
  /channels[?refresh=1]            current channel list (live from Init7, 5 min cache)
  /play?channel=<name|nr|pk>       start a channel (optional &source=auto|multicast|hls; auto = multicast, then HLS)
  /stop                            stop playback
  /status                          state of mpv and HDMI
  /events                          the same as server-sent events: at once, on every change and every few seconds (web UI)
  /volume?v=0-130 | ?d=+5/-5       mpv volume (absolute or relative)
  /mute                            toggle mute
  /environment                     live view of HDMI ports, audio devices and the effective settings
  /favorites                       favorite channel ids (POST saves them, Web UI only)
  /icon?u=<logo url>               channel logo (only Init7 logo URLs; cached)
  /track?type=audio|sub&id=<n|off> switch audio / subtitle track of the running stream
  /osd?on=1|0[&lang=de|en|fr|it]  technical info as an overlay on the TV (on/off for everyone)
  /key?k=<key>                     remote control key for the TV menu (ok, up, down, left, right, back, ch_up, ch_down, info, stop, 0-9)
  /nerd                            all technical details (codec, bitrate, dropped frames, DRM mode/planes, clock, mpv log excerpt)
  /support                         the same plus versions and environment as Markdown for a GitHub issue; secrets masked (****)
  /settings                        (Web UI only) editable settings, live choices, pending-restart flag; POST saves them

Web UI: if TV7_UI_PORT is set, a second listener serves a small media player page (ui.html) and the same
endpoints for Home Assistant Ingress. It only accepts connections from the Supervisor (TV7_UI_ALLOW), so no
token is needed there: Home Assistant authenticates the user.

The API listens on 127.0.0.1 only: Home Assistant on the same device reaches it, nothing on the network does (no token needed).

Only streams from the Init7 channel list are played (no free-form URLs). If a stream does not start,
a second attempt is made; for multicast, the next step is a fallback to HLS. The HDMI state is only read
(the app runs with protection mode on, /sys is read-only).
"""

import os
import signal
import sys
import threading
import time
from http.server import ThreadingHTTPServer

# the package tv7 next to this file (also with python -I)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tv7 import cec, config, mpvclient, mpvhost, player, settings, tvdraw, tvinfo, tvmenu, web  # noqa: E402

if __name__ == "__main__":
    # control.py                    production (run.sh): starts and supervises mpv
    # control.py <socket> <port>    attach to an mpv someone else runs (tests, dev/run-web.sh)
    attach = len(sys.argv) > 2
    mpvclient.SOCK, port = (sys.argv[1], int(sys.argv[2])) if attach else ("/tmp/mpv.sock", 8765)
    if not attach and "TV7_UI_PORT" not in os.environ:
        config.UI_PORT = 8099  # Home Assistant Ingress (web UI in the sidebar)
    signal.signal(signal.SIGTERM, mpvhost.stop_app)
    signal.signal(signal.SIGINT, mpvhost.stop_app)
    # Lower layers report events through these hooks; the modules that act on them sit above (see docs/DEVELOPMENT.md).
    cec.handlers.update(
        key=tvmenu.handle_key,
        standby=player.tv_standby,
        shown=player.tv_shown,
        playing=lambda: bool(player.state.current["pk"]),
    )
    player.handlers["resume"] = tvmenu.resume
    mpvclient.on_idle.append(tvinfo.playback_ended)
    tvdraw.on_logo_ready.append(tvmenu.logo_ready)
    settings.init_settings()
    mpvclient.mpv_log()  # collect mpv's log from the start (nerd mode, support text)
    threading.Thread(target=player.watcher, daemon=True).start()
    threading.Thread(target=tvmenu.osd_loop, daemon=True).start()
    threading.Thread(target=tvdraw.ha_language_loop, daemon=True).start()
    threading.Thread(
        target=lambda: cec.cec_setup(settings.current_values().get("cec", "auto") != "off"), daemon=True
    ).start()
    # only Home Assistant on this device, never the network
    api_server = ThreadingHTTPServer(("127.0.0.1", port), web.H)
    threading.Thread(target=api_server.serve_forever, daemon=True).start()
    if config.UI_PORT:
        try:  # only on the Supervisor's network, not on the LAN (host network)
            ui_server = ThreadingHTTPServer((config.UI_BIND, config.UI_PORT), web.UiH)
        except OSError as e:
            config.log_line(
                f"Web UI: cannot listen on {config.UI_BIND} ({e}); listening on all interfaces, only the Supervisor is let in"
            )
            ui_server = ThreadingHTTPServer(("0.0.0.0", config.UI_PORT), web.UiH)
        threading.Thread(target=ui_server.serve_forever, daemon=True).start()
    if attach:
        while True:
            time.sleep(3600)
    mpvhost.run_player()

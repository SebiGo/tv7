"""The HTTP API (Home Assistant on this device) and the web UI (Home Assistant Ingress): endpoints, status, events.

Every endpoint is a function in a routing table (GET, UI_POST, UI_STATIC). It gets the request handler and the query and
returns (status code, JSON body), or None when it wrote the answer itself (logos, /events). Errors become answers in one
place (_dispatch): KeyError 404, ValueError 400, PermissionError 403, anything else 502."""

import json
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

from tv7 import cec, config, display, init7, mpvclient, player, settings, supervisor, support, system, tvinfo, tvmenu


def status_view():
    """What the web UI shows: what plays, HDMI, volume, tracks, output, load, automatic stops, pending restart."""
    return {
        "hdmi": display.hdmi_status(),
        "playing": mpvclient.playing(),
        "title": mpvclient.prop("media-title"),
        "video": mpvclient.prop("video-codec"),
        "audio": mpvclient.prop("audio-codec-name"),
        "audio_out": mpvclient.prop("current-ao"),
        "volume": mpvclient.prop("volume"),
        "mute": mpvclient.prop("mute"),
        "channel": player.state.current["name"],
        "pk": player.state.current["pk"],
        "source": player.state.current["source"],
        "stream": {
            "w": mpvclient.prop("video-params/w"),
            "h": mpvclient.prop("video-params/h"),
            "fps": mpvclient.prop("container-fps") or mpvclient.prop("estimated-vf-fps"),
        },
        "output": {
            "w": mpvclient.prop("osd-width"),
            "h": mpvclient.prop("osd-height"),
            "hz": mpvclient.prop("display-fps"),
        },
        "version": config.app_version(),
        "vo": mpvclient.prop("current-vo"),
        "hwdec": mpvclient.prop("hwdec-current"),
        "system": system.system_load(),
        "audio_tracks": mpvclient.tracks()["audio"],
        "sub_tracks": mpvclient.tracks()["sub"],
        "autostopped": dict(player.state.autostopped) or None,
        "hdmi_stopped": {"channel": player.state.hdmi_stopped["name"]} if player.state.hdmi_stopped else None,
        "pending_restart": settings.pending_restart(),
        "osd": tvinfo.osd_state["on"],
    }


def _arg(q, name, choices=None):
    """A query parameter; ValueError (400) when it is missing or not one of choices."""
    if name not in q:
        raise ValueError(f"{name} missing")
    v = q[name][0]
    if choices and v not in choices:
        raise ValueError(f"{name}: {' or '.join(choices)}")
    return v


def get_channels(h, q):
    return 200, [
        {
            "nr": c.get("ordernum"),
            "name": c["name"],
            "pk": c["pk"],
            "hd": c.get("hd"),
            "multicast": init7.multicast_url(c.get("src")) is not None,
            "hls": c.get("has_hls"),
            "list": c.get("list", "tv7"),
            "logo": c.get("logo"),
        }
        for c in init7.channels(force="refresh" in q)
    ]


def get_play(h, q):
    channel, src = _arg(q, "channel"), q.get("source", ["auto"])[0]
    if src not in ("auto", "multicast", "hls"):
        raise ValueError("source: auto, multicast or hls")
    player.touch()
    res = player.play(init7.find_channel(channel), src)
    return (200 if res["ok"] else 502), res


def get_stop(h, q):
    player.touch()
    return 200, player.stop_playback()


def get_key(h, q):
    k = _arg(q, "k")
    if k not in cec.KEYS:
        raise ValueError("k: " + ", ".join(sorted(cec.KEYS)))
    tvmenu.handle_key(k)
    menu = tvmenu.menu
    return 200, {"menu": menu["open"], "tab": tvmenu.TABS[menu["tab"]] if menu["open"] else None}


def get_volume(h, q):
    if "v" not in q and "d" not in q:
        raise ValueError("v (0-130) or d (+/- change) missing")
    player.touch()
    vol = float(q["v"][0]) if "v" in q else (mpvclient.prop("volume") or 0) + float(q["d"][0])
    return 200, mpvclient.mpv("set_property", "volume", max(0.0, min(130.0, vol)))


def get_mute(h, q):
    player.touch()
    return 200, mpvclient.mpv("cycle", "mute")


def get_track(h, q):
    kind, tid = _arg(q, "type", ("audio", "sub")), _arg(q, "id")
    if tid != "off" and not tid.isdigit():
        raise ValueError("id: a track number or off")
    player.touch()
    return 200, mpvclient.mpv("set_property", "aid" if kind == "audio" else "sid", "no" if tid == "off" else int(tid))


def get_osd(h, q):
    if "on" in q:
        on = _arg(q, "on", ("1", "0"))
        return 200, tvinfo.set_osd(on == "1", q.get("lang", [""])[0][:2].lower() or None)
    return 200, {"on": tvinfo.osd_state["on"]}


def get_icon(h, q):
    data, ctype = init7.logo_file(_arg(q, "u"))  # PermissionError (403) for URLs outside the Init7 logos
    h.send_bytes(data, ctype, "public, max-age=604800")


def get_events(h, q):
    """Server-sent events: the status (as /status) at once, then whenever it changes, and at least every config.EVENTS_S
    (CPU load, temperature and dropped frames change all the time). Ends when the client goes away."""
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream")
    h.send_header("Cache-Control", "no-cache")
    h.send_header("X-Accel-Buffering", "no")
    h.end_headers()
    seen, last = None, None
    try:
        while True:
            seen = mpvclient.wait_change(seen, config.EVENTS_S)
            data = json.dumps(status_view(), ensure_ascii=False)
            h.wfile.write(f"data: {data}\n\n".encode() if data != last else b": still here\n\n")
            h.wfile.flush()
            last = data
    except OSError:
        return


GET = {
    "/health": lambda h, q: (200, {"ok": True}),
    "/status": lambda h, q: (200, status_view()),
    "/events": get_events,
    "/channels": get_channels,
    "/play": get_play,
    "/stop": get_stop,
    "/volume": get_volume,
    "/mute": get_mute,
    "/track": get_track,
    "/key": get_key,
    "/osd": get_osd,
    "/icon": get_icon,
    "/favorites": lambda h, q: (200, {"favorites": init7.load_favorites()}),
    "/settings": lambda h, q: (200, settings.settings_view(q.get("lang", ["en"])[0][:2].lower())),
    "/environment": lambda h, q: (200, system.environment()),
    "/nerd": lambda h, q: (200, system.nerd()),
    "/support": lambda h, q: (200, {"text": support.support_text()}),
}


def post_settings(h, body):
    if not isinstance(body, dict) or not isinstance(body.get("values"), dict):
        raise ValueError('body: {"values": {...}}')
    return 200, settings.save_settings(body["values"])


def post_favorites(h, body):
    if not isinstance(body, dict):
        raise ValueError('body: {"favorites": [...]}')
    return 200, {"favorites": init7.save_favorites(body.get("favorites"))}


def post_restart(h, body):
    if not supervisor.available():
        return 502, {"error": "restart needs the Supervisor API (hassio_api)"}
    h.reply(200, {"ok": True})
    supervisor.restart_app()


UI_POST = {"/settings": post_settings, "/favorites": post_favorites, "/restart": post_restart}
# the page (its texts come from i18n/<lang>.json) and the logo
UI_STATIC = {
    "/": ("UI_FILE", "text/html; charset=utf-8"),
    "/index.html": ("UI_FILE", "text/html; charset=utf-8"),
    "/logo.png": ("UI_LOGO", "image/png"),
}


class H(BaseHTTPRequestHandler):
    """The API: listens on 127.0.0.1 only (control.py), so only Home Assistant on this device reaches it."""

    def reply(self, code, obj):
        self.send_bytes(json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", code=code)

    def send_bytes(self, data, ctype, cache=None, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if cache:
            self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, routes, arg):
        fn = routes.get(urllib.parse.urlparse(self.path).path)
        if not fn:
            return self.reply(404, {"error": "unknown endpoint"})
        try:
            res = fn(self, arg)
        except KeyError as e:
            res = 404, {"error": str(e).strip("\"'")}
        except ValueError as e:
            res = 400, {"error": str(e)}
        except PermissionError as e:
            res = 403, {"error": str(e)}
        except Exception as e:
            res = 502, {"error": str(e)}
        if res is not None:
            self.reply(*res)

    def do_GET(self):
        self._dispatch(GET, urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))

    def log_message(self, *a):
        pass


class UiH(H):
    """The Ingress web UI: the same endpoints, plus the page and the POST endpoints; only the Supervisor may connect, so
    Home Assistant has authenticated the user."""

    def allowed(self):
        if not config.ui_client_ok(self.client_address[0]):
            self.reply(403, {"error": "forbidden"})
            return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        static = UI_STATIC.get(urllib.parse.urlparse(self.path).path)
        if not static:
            return super().do_GET()
        path = getattr(config, static[0])
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return self.reply(404, {"error": "file missing"})
        if path == config.UI_FILE:
            data = data.replace(b"/*I18N*/{}", config.UI_TEXTS)
        self.send_bytes(data, static[1], "no-cache")

    def do_POST(self):
        if not self.allowed():
            return
        # A custom header makes cross-site form posts impossible (browsers would need a CORS preflight, which is never
        # granted).
        if self.headers.get("X-TV7-UI") != "1":
            return self.reply(403, {"error": "missing X-TV7-UI header"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n) or b"{}") if 0 <= n <= 65536 else None
        except ValueError as e:
            return self.reply(400, {"error": str(e)})
        self._dispatch(UI_POST, body)

"""The HTTP API (Home Assistant on this device) and the web UI (Home Assistant Ingress): endpoints, status, events."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

from tv7 import cec, config, display, init7, mpvclient, player, settings, supervisor, support, system, tvosd

EVENTS_S = float(os.environ.get("TV7_EVENTS_S", "3"))  # /events: at least this often (live values)


def status_view():
    """What the web UI shows: what plays, HDMI, volume, tracks, output, system load, automatic stops, pending restart."""
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
        "osd": tvosd.osd_state["on"],
    }


class H(BaseHTTPRequestHandler):
    def reply(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self, q):
        return True  # the API listens on 127.0.0.1 only (see main)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/health":
            return self.reply(200, {"ok": True})
        if not self.authorized(q):
            return self.reply(401, {"error": "Token missing or wrong"})
        try:
            if u.path == "/channels":
                return self.reply(
                    200,
                    [
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
                    ],
                )
            if u.path == "/play" and "channel" in q:
                src = q.get("source", ["auto"])[0]
                if src not in ("auto", "multicast", "hls"):
                    return self.reply(400, {"error": "source: auto, multicast or hls"})
                player.touch()
                res = player.play(init7.find_channel(q["channel"][0]), src)
                return self.reply(200 if res["ok"] else 502, res)
            if u.path == "/stop":
                player.touch()
                return self.reply(200, player.stop_playback())
            if u.path == "/key" and "k" in q:
                if q["k"][0] not in cec.KEYS:
                    return self.reply(400, {"error": "k: " + ", ".join(sorted(cec.KEYS))})
                tvosd.handle_key(q["k"][0])
                return self.reply(
                    200,
                    {"menu": tvosd.menu["open"], "tab": tvosd.TABS[tvosd.menu["tab"]] if tvosd.menu["open"] else None},
                )
            if u.path == "/volume" and ("v" in q or "d" in q):
                player.touch()
                vol = float(q["v"][0]) if "v" in q else (mpvclient.prop("volume") or 0) + float(q["d"][0])
                return self.reply(200, mpvclient.mpv("set_property", "volume", max(0.0, min(130.0, vol))))
            if u.path == "/mute":
                player.touch()
                return self.reply(200, mpvclient.mpv("cycle", "mute"))
            if u.path == "/settings":
                return self.reply(200, settings.settings_view(q.get("lang", ["en"])[0][:2].lower()))
            if u.path == "/favorites":
                return self.reply(200, {"favorites": init7.load_favorites()})
            if u.path == "/icon" and "u" in q:
                try:
                    data, ctype = init7.logo_file(q["u"][0])
                except PermissionError as e:
                    return self.reply(403, {"error": str(e)})
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=604800")
                self.end_headers()
                return self.wfile.write(data)
            if u.path == "/track" and "type" in q and "id" in q:
                kind, tid = q["type"][0], q["id"][0]
                if kind not in ("audio", "sub"):
                    return self.reply(400, {"error": "type: audio or sub"})
                if tid != "off" and not tid.isdigit():
                    return self.reply(400, {"error": "id: a track number or off"})
                player.touch()
                return self.reply(
                    200,
                    mpvclient.mpv(
                        "set_property", "aid" if kind == "audio" else "sid", "no" if tid == "off" else int(tid)
                    ),
                )
            if u.path == "/environment":
                return self.reply(200, system.environment())
            if u.path == "/nerd":
                return self.reply(200, system.nerd())
            if u.path == "/osd":
                if "on" in q:
                    if q["on"][0] not in ("0", "1"):
                        return self.reply(400, {"error": "on: 1 or 0"})
                    return self.reply(200, tvosd.set_osd(q["on"][0] == "1", q.get("lang", [""])[0][:2].lower() or None))
                return self.reply(200, {"on": tvosd.osd_state["on"]})
            if u.path == "/support":
                return self.reply(200, {"text": support.support_text()})
            if u.path == "/events":
                return self.events()
            if u.path == "/status":
                return self.reply(200, status_view())
            self.reply(404, {"error": "unknown endpoint"})
        except KeyError as e:
            self.reply(404, {"error": str(e).strip("\"'")})
        except ValueError as e:
            self.reply(400, {"error": str(e)})
        except Exception as e:
            self.reply(502, {"error": str(e)})

    def events(self):
        """Server-sent events: the status (as /status) at once, then whenever it changes, and at least every EVENTS_S (CPU load,
        temperature and dropped frames change all the time). Ends when the client goes away."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        seen, last = None, None
        try:
            while True:
                seen = mpvclient.wait_change(seen, EVENTS_S)
                data = json.dumps(status_view(), ensure_ascii=False)
                self.wfile.write(f"data: {data}\n\n".encode() if data != last else b": still here\n\n")
                self.wfile.flush()
                last = data
        except OSError:
            return

    def log_message(self, *a):
        pass


class UiH(H):
    """Handler for the Ingress web UI: same endpoints, plus the page itself; only the Supervisor may connect."""

    def authorized(self, q):
        return config.ui_client_ok(self.client_address[0])

    def do_POST(self):
        if not config.ui_client_ok(self.client_address[0]):
            return self.reply(403, {"error": "forbidden"})
        # A custom header makes cross-site form posts impossible (browsers would need a CORS preflight, which is never granted).
        if self.headers.get("X-TV7-UI") != "1":
            return self.reply(403, {"error": "missing X-TV7-UI header"})
        path = urllib.parse.urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n) or b"{}") if 0 <= n <= 65536 else None
            if path == "/settings":
                if not isinstance(body, dict) or not isinstance(body.get("values"), dict):
                    return self.reply(400, {"error": 'body: {"values": {...}}'})
                return self.reply(200, settings.save_settings(body["values"]))
            if path == "/favorites":
                if not isinstance(body, dict):
                    return self.reply(400, {"error": 'body: {"favorites": [...]}'})
                return self.reply(200, {"favorites": init7.save_favorites(body.get("favorites"))})
            if path == "/restart":
                if not supervisor.available():
                    return self.reply(502, {"error": "restart needs the Supervisor API (hassio_api)"})
                self.reply(200, {"ok": True})
                supervisor.restart_app()
                return
            return self.reply(404, {"error": "unknown endpoint"})
        except ValueError as e:
            return self.reply(400, {"error": str(e)})
        except Exception as e:
            return self.reply(502, {"error": str(e)})

    def do_GET(self):
        if not config.ui_client_ok(self.client_address[0]):
            return self.reply(403, {"error": "forbidden"})
        path = urllib.parse.urlparse(self.path).path
        static = {
            "/": (config.UI_FILE, "text/html; charset=utf-8"),
            "/index.html": (config.UI_FILE, "text/html; charset=utf-8"),
            "/logo.png": (config.UI_LOGO, "image/png"),
        }
        if path in static:
            try:
                body = open(static[path][0], "rb").read()
            except OSError:
                return self.reply(404, {"error": "file missing"})
            if static[path][0] == config.UI_FILE:  # the page's texts come from i18n/<lang>.json
                body = body.replace(b"/*I18N*/{}", config.UI_TEXTS)
            self.send_response(200)
            self.send_header("Content-Type", static[path][1])
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return self.wfile.write(body)
        super().do_GET()

"""The fake world the tests run in: Init7 channel list and logos, the Supervisor, HDMI sysfs, modetest and mpv (mock_mpv.py),
plus App, which starts control.py against them.

Nothing here touches hardware or the network (except the real Init7 channel list with pytest --live).
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from mock_mpv import MockMpv

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(HERE, "..")
ROOTFS = os.path.join(APP_DIR, "rootfs")
CONTROL = os.path.join(ROOTFS, "control.py")

HLS = "https://api.tv.init7.net/api/live/?channel="
CHANNELS = [
    {"pk": "pk-srf1", "name": "SRF 1", "ordernum": 1102, "hd": True, "visible": True,
     "src": "udp://@233.50.230.80:5000", "has_hls": True, "hls_src": HLS + "pk-srf1"},
    {"pk": "pk-srf2", "name": "SRF zwei", "ordernum": 1104, "hd": True, "visible": True,
     "src": "udp://@233.50.230.212:5000", "has_hls": True, "hls_src": HLS + "pk-srf2"},
    {"pk": "pk-srfi", "name": "SRF info", "ordernum": 1106, "hd": True, "visible": True,
     "src": "udp://@233.50.230.99:5000", "has_hls": True, "hls_src": HLS + "pk-srfi"},
    {"pk": "pk-bad", "name": "Evil", "ordernum": 9998, "hd": False, "visible": True,
     "src": "udp://@10.0.0.5:5000", "has_hls": True, "hls_src": "http://evil.example/x.m3u8"},
    {"pk": "pk-hid", "name": "Hidden", "ordernum": 9999, "hd": False, "visible": False,
     "src": "udp://@233.1.1.1:5000", "has_hls": True, "hls_src": HLS + "pk-hid"},
]  # fmt: skip
SRG_MC = """#EXTM3U
#EXTINF:0 tvg-logo="https://x/1.png" "tvg-name="SRF1.ch" tvg-chno="1108" group-title="Deutsch", SRF 1 FHD
udp://@233.50.230.1:5000
#EXTINF:0 tvg-logo="https://x/2.png" "tvg-name="RTS1.ch" tvg-chno="2109" group-title="Français", RTS 1 FHD
udp://@233.50.230.84:5000
"""
SRG_HLS = """#EXTM3U
#EXTINF:0 tvg-logo="https://x/1.png" "tvg-name="SRF1.ch" tvg-chno="1108" group-title="Deutsch", SRF 1 FHD
https://vtvapi03.sys.init7.net/api/live/?channel=srg-1
#EXTINF:0 tvg-logo="https://x/2.png" "tvg-name="RTS1.ch" tvg-chno="2109" group-title="Français", RTS 1 FHD
http://evil.example/rts1.m3u8
"""
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63fcffff3f0005fe02fea75b1d6a"
    "0000000049454e44ae426082"
)
MODETEST_OUT = """Connectors:
id	encoder	status		name		size (mm)	modes	encoders
32	31	connected	HDMI-A-1       	700x390		5	31
  modes:
	index name refresh (Hz) hdisp hss hse htot vdisp vss vse vtot
  #0 3840x2160 60.00 3840 4016 4104 4400 2160 2168 2178 2250 594000 flags: phsync, pvsync; type: preferred, driver
  #1 3840x2160 50.00 3840 4896 4984 5280 2160 2168 2178 2250 594000 flags: phsync, pvsync; type: driver
  #2 1920x1080i 50.00 1920 2448 2492 2640 1080 1084 1094 1125 74250 flags: phsync, pvsync, interlace; type: driver
  #3 1920x1080 50.00 1920 2448 2492 2640 1080 1084 1094 1125 148500 flags: phsync, pvsync; type: driver
  #4 1920x1080 59.94 1920 2008 2052 2200 1080 1084 1089 1125 148352 flags: phsync, pvsync; type: driver
  props:
"""
MPV_LOG = [
    ("vo/drm", "mock line 0"),
    ("vo/drm", "mock line 1"),
    ("vo/drm", "mock line 2 from 192.168.1.20 https://api.tv.init7.net/api/live/?channel=x&sig=abc Bearer eyJ.secret"),
]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(handler):
    srv = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _reply(h, code, body, ctype=None):
    h.send_response(code)
    if ctype:
        h.send_header("Content-Type", ctype)
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


class World:
    """One fake environment for the whole test session. `state` is what the fake mpv saw and does (see mock_mpv.py, plus
    "scenario": ok | never | multicast_fails | needs_hdmi, and "cable": whether a display answers HDMI detection), `sup` what
    the fake Supervisor received."""

    def __init__(self, live=False):
        self.live = live
        self.tmp = tempfile.mkdtemp(prefix="tv7-test-")
        self.sock, self.drm = f"{self.tmp}/mpv.sock", f"{self.tmp}/drm"
        self.state = {"scenario": "", "loaded": None, "t0": 0.0, "loads": 0, "cable": True}
        self.sup = {"options": None, "auth": None, "restarts": 0, "reject": False, "core": None}
        self._channel_api()
        self._supervisor()
        self._hdmi()
        self.write_modetest("modetest", MODETEST_OUT)
        # video_refresh, api_token and subtitles are not in the schema: saving must drop them
        with open(f"{self.tmp}/options.json", "w") as f:
            json.dump(
                {"hdmi_port": "auto", "video_refresh": "50", "api_token": "secret-should-not-show", "subtitles": True},
                f,
            )
        MockMpv(self.sock, self.state, can_start=self._can_start, log_lines=MPV_LOG).serve()
        self.env = dict(
            os.environ,
            TV7_TRANSLATIONS=os.path.join(APP_DIR, "translations"),
            TV7_DRM_DIR=self.drm,
            TV7_START_TIMEOUT="2",
            TV7_UI_PORT="0",
            TV7_SRG_FHD="false",
            TV7_VERSION="9.9.9",
            TV7_HW_AVAILABLE="yes",
            TV7_MODE_WAIT_S="1",
            TV7_FAVORITES=f"{self.tmp}/favorites.json",
            TV7_LOGO_DIR=f"{self.tmp}/logos",
            TV7_LOGO_PREFIX=f"{self.api_url}/media/logos/",
            TV7_UI_ALLOW="127.0.0.1",
            TV7_UI_BIND="127.0.0.1",
            TV7_OPTIONS=f"{self.tmp}/options.json",
            SUPERVISOR_TOKEN="tok",
            TV7_SUPERVISOR=self.sup_url,
            TV7_MODETEST=f"{self.tmp}/modetest",
            TV7_HDMI_OFF_S="600",
            TV7_EVENTS_S="30",
            TV7_CEC_GLOB=f"{self.tmp}/no-cec*",
            TV7_DIGIT_S="0.4",
            TV7_MENU_TIMEOUT_S="2.5",
            TV7_OSD_CACHE=f"{self.tmp}/osd",
        )
        if not live:
            self.env.update(
                TV7_API=f"{self.api_url}/",
                TV7_SRG_MC_URL=f"{self.api_url}/srg-mc.m3u",
                TV7_SRG_HLS_URL=f"{self.api_url}/srg-hls.m3u",
            )

    # --- Fake Init7: channel list, SRG Full HD lists, logos ---
    def _channel_api(self):
        class Api(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/media/logos/"):
                    return _reply(self, 200, PNG, "image/png")
                if self.path.startswith("/srg-"):
                    return _reply(self, 200, (SRG_MC if "mc" in self.path else SRG_HLS).encode())
                body = json.dumps({"count": len(CHANNELS), "next": None, "results": CHANNELS}).encode()
                _reply(self, 200, body, "application/json")

            def log_message(self, *a):
                pass

        srv = _serve(Api)
        self.api_url = f"http://127.0.0.1:{srv.server_port}"
        for c in CHANNELS:
            c["logo"] = f"{self.api_url}/media/logos/{c['pk']}.png"

    # --- Fake Supervisor: info, Core config, app log, options, restart ---
    def _supervisor(self):
        sup = self.sup

        class Sup(BaseHTTPRequestHandler):
            def do_GET(self):
                sup["range"] = self.headers.get("Range")
                if self.path == "/info":
                    info = {"hassos": "16.3", "homeassistant": "2026.11.2", "supervisor": "2026.11.0",
                            "machine": "raspberrypi5-64", "arch": "aarch64"}  # fmt: skip
                    data = json.dumps({"result": "ok", "data": info}).encode()
                elif self.path == "/core/api/config" and sup.get("core") is not None:
                    data = json.dumps(sup["core"]).encode()
                elif self.path == "/addons/self/logs":
                    data = (
                        b"\x1b[32m>>> Video output (auto): gpu\x1b[0m\n>>> Audio device (auto): pulse/x\n"
                        b"connect from 10.1.2.3 token=abc\n"
                    )
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                _reply(self, 200, data)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                code, out = 200, {"result": "ok", "data": {}}
                if self.path == "/addons/self/options":
                    sup["auth"] = self.headers.get("Authorization")
                    if sup["reject"]:
                        code, out = 400, {"result": "error", "message": "invalid option"}
                    else:
                        sup["options"] = body["options"]
                elif self.path == "/addons/self/restart":
                    sup["restarts"] += 1
                _reply(self, code, json.dumps(out).encode())

            def log_message(self, *a):
                pass

        self.sup_url = f"http://127.0.0.1:{_serve(Sup).server_port}"

    # --- Fake HDMI sysfs (two connectors) and the kernel's answer to detection ---
    def _hdmi(self):
        for n in ("1", "2"):
            os.makedirs(f"{self.drm}/card1-HDMI-A-{n}")
        self.hdmi("connected")
        with open(f"{self.drm}/card1-HDMI-A-1/modes", "w") as f:
            f.write("1920x1080\n1920x1080i\n1280x720\n1920x1080\n")

        def watch():  # detect -> connected (if a display answers), off -> disconnected
            while True:
                v = self.hdmi_read()
                if v == "detect":
                    self.hdmi("connected" if self.state["cable"] else "disconnected")
                elif v == "off":
                    self.hdmi("disconnected")
                time.sleep(0.05)

        threading.Thread(target=watch, daemon=True).start()

    def hdmi(self, status):
        for n in ("1", "2"):
            with open(f"{self.drm}/card1-HDMI-A-{n}/status", "w") as f:
                f.write(status)

    def hdmi_read(self):
        with open(f"{self.drm}/card1-HDMI-A-1/status") as f:
            return f.read().strip()

    def write_modetest(self, name, text):
        """A fake modetest program at <tmp>/<name> that prints text."""
        with open(f"{self.tmp}/{name}.txt", "w") as f:
            f.write(text)
        with open(f"{self.tmp}/{name}", "w") as f:
            f.write(f"#!/bin/sh\ncat {self.tmp}/{name}.txt\n")
        os.chmod(f"{self.tmp}/{name}", 0o755)
        return f"{self.tmp}/{name}"

    def _can_start(self, url):
        sc = self.state["scenario"]
        if sc == "never":
            return False
        if sc == "multicast_fails" and url.startswith("udp://"):
            return False
        if sc == "needs_hdmi" and self.hdmi_read() != "connected":
            return False
        return True

    def ready(self, **extra):
        """Every channel starts, a display is connected; extra goes into the mpv state (e.g. hw=False, fps=50.0)."""
        self.state.update({"scenario": "ok", "cable": True, "loads": 0, "novideo": False, **extra})
        self.hdmi("connected")

    def options_file(self, name, values):
        path = f"{self.tmp}/{name}"
        with open(path, "w") as f:
            json.dump(values, f)
        return path


class App:
    """control.py attached to the fake mpv, with its API on a free port (and the web UI with ui=True). env overrides the
    world's environment. Use as a context manager or call stop()."""

    def __init__(self, world, ui=False, **env):
        self.world = world
        self.port = free_port()
        self.ui_port = free_port() if ui else 0
        full_env = dict(world.env, TV7_UI_PORT=str(self.ui_port), **env)
        self.proc = subprocess.Popen([sys.executable, "-I", CONTROL, world.sock, str(self.port)], env=full_env)
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1).read()
                break
            except OSError:
                time.sleep(0.1)
        else:
            self.stop()
            raise RuntimeError("control.py did not answer /health")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def url(self, path, ui=False):
        return f"http://127.0.0.1:{self.ui_port if ui else self.port}{path}"

    def get(self, path, ui=False):
        """GET a JSON endpoint: (status code, decoded body)."""
        try:
            r = urllib.request.urlopen(self.url(path, ui), timeout=90)
            return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def page(self, path):
        """GET from the web UI port as text: (status code, body)."""
        try:
            r = urllib.request.urlopen(self.url(path, ui=True), timeout=30)
            return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def post(self, path, body, headers=None):
        """POST JSON to the web UI port (with the X-TV7-UI header unless headers override it)."""
        h = {"Content-Type": "application/json", "X-TV7-UI": "1", **(headers or {})}
        req = urllib.request.Request(self.url(path, ui=True), data=json.dumps(body).encode(), headers=h, method="POST")
        try:
            r = urllib.request.urlopen(req, timeout=30)
            return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def events(self, n, during=None, ui=False):
        """Read n status messages from /events; during() runs after the first one. Returns ([(status, time)], content type)."""
        resp = urllib.request.urlopen(self.url("/events", ui), timeout=10)
        out, t0 = [], time.time()
        while len(out) < n and time.time() - t0 < 8:
            line = resp.readline().decode()
            if line.startswith("data: "):
                out.append((json.loads(line[6:]), time.time()))
                if len(out) == 1 and during:
                    during()
        resp.close()
        return out, resp.headers.get("Content-Type")


def wait_for(cond, timeout=3.0, step=0.1):
    """Poll cond() until it is true or the time is up; returns its last value."""
    end = time.time() + timeout
    while True:
        v = cond()
        if v or time.time() >= end:
            return v
        time.sleep(step)

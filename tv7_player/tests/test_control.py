"""Tests for control.py with a mock mpv, a mock HDMI sysfs and a local fake channel list.
Usage:   python3 tests/test_control.py            (offline, deterministic)
         python3 tests/test_control.py --live     (real Init7 channel list instead of the fake)
"""
import hashlib
import re
import json, os, socket, subprocess, sys, tempfile, threading, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

LIVE = "--live" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
CONTROL = os.path.join(HERE, "..", "rootfs", "control.py")
tmp = tempfile.mkdtemp()
SOCK, DRM = f"{tmp}/mpv.sock", f"{tmp}/drm"
for n in ("1", "2"):
    os.makedirs(f"{DRM}/card1-HDMI-A-{n}")
state = {"scenario": "", "loaded": None, "t0": 0.0, "loads": 0, "cable": True}

# --- Fake channel list (HTTP) -------------------------------------------------
HLS = "https://api.tv.init7.net/api/live/?channel="
CHANNELS = [
    {"pk": "pk-srf1", "name": "SRF 1", "ordernum": 1102, "hd": True, "visible": True, "src": "udp://@233.50.230.80:5000", "has_hls": True, "hls_src": HLS + "pk-srf1"},
    {"pk": "pk-srf2", "name": "SRF zwei", "ordernum": 1104, "hd": True, "visible": True, "src": "udp://@233.50.230.212:5000", "has_hls": True, "hls_src": HLS + "pk-srf2"},
    {"pk": "pk-srfi", "name": "SRF info", "ordernum": 1106, "hd": True, "visible": True, "src": "udp://@233.50.230.99:5000", "has_hls": True, "hls_src": HLS + "pk-srfi"},
    {"pk": "pk-bad", "name": "Evil", "ordernum": 9998, "hd": False, "visible": True, "src": "udp://@10.0.0.5:5000", "has_hls": True, "hls_src": "http://evil.example/x.m3u8"},
    {"pk": "pk-hid", "name": "Hidden", "ordernum": 9999, "hd": False, "visible": False, "src": "udp://@233.1.1.1:5000", "has_hls": True, "hls_src": HLS + "pk-hid"},
]
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
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63fcffff3f0005fe02fea75b1d6a0000000049454e44ae426082")
class Api(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/media/logos/"):
            self.send_response(200); self.send_header("Content-Type", "image/png"); self.send_header("Content-Length", str(len(PNG))); self.end_headers(); self.wfile.write(PNG); return
        if self.path.startswith("/srg-"):
            body = (SRG_MC if "mc" in self.path else SRG_HLS).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        body = json.dumps({"count": len(CHANNELS), "next": None, "results": CHANNELS}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
api = HTTPServer(("127.0.0.1", 0), Api)
for _c in CHANNELS: _c["logo"] = f"http://127.0.0.1:{api.server_port}/media/logos/{_c['pk']}.png"
threading.Thread(target=api.serve_forever, daemon=True).start()

# --- Fake HDMI (sysfs) -------------------------------------------------------
def hdmi_write(v):
    for n in ("1", "2"): open(f"{DRM}/card1-HDMI-A-{n}/status", "w").write(v)
def hdmi_read(): return open(f"{DRM}/card1-HDMI-A-1/status").read().strip()
hdmi_write("connected")
open(f"{DRM}/card1-HDMI-A-1/modes", "w").write("1920x1080\n1920x1080i\n1280x720\n1920x1080\n")
open(f"{tmp}/options.json", "w").write(json.dumps({"hdmi_port": "auto", "video_refresh": "50", "api_token": "secret-should-not-show", "subtitles": True}))
def hdmi_watch():                 # simulates the kernel: detect -> connected (if cable/device present), off -> disconnected
    while True:
        v = hdmi_read()
        if v == "detect": hdmi_write("connected" if state["cable"] else "disconnected")
        elif v == "off": hdmi_write("disconnected")
        time.sleep(0.05)
threading.Thread(target=hdmi_watch, daemon=True).start()

# --- Fake Supervisor (options + restart) and fake modetest ----------------------------
sup = {"options": None, "auth": None, "restarts": 0, "reject": False}
class Sup(BaseHTTPRequestHandler):
    def do_GET(self):
        sup["range"] = self.headers.get("Range")
        if self.path == "/info":
            data = json.dumps({"result": "ok", "data": {"hassos": "16.3", "homeassistant": "2026.11.2", "supervisor": "2026.11.0", "machine": "raspberrypi5-64", "arch": "aarch64"}}).encode()
        elif self.path == "/core/api/config" and sup.get("core") is not None:
            data = json.dumps(sup["core"]).encode()
        elif self.path == "/addons/self/logs":
            data = "\x1b[32m>>> Video output (auto): gpu\x1b[0m\n>>> Audio device (auto): pulse/x\nconnect from 10.1.2.3 token=abc\n".encode()
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
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
        data = json.dumps(out).encode(); self.send_response(code); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *a): pass
sup_srv = HTTPServer(("127.0.0.1", 0), Sup); threading.Thread(target=sup_srv.serve_forever, daemon=True).start()
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
open(f"{tmp}/modetest.txt", "w").write(MODETEST_OUT)
open(f"{tmp}/modetest", "w").write(f"#!/bin/sh\ncat {tmp}/modetest.txt\n"); os.chmod(f"{tmp}/modetest", 0o755)

# --- Fake mpv (IPC socket) ---------------------------------------------------
def can_start(url):
    sc = state["scenario"]
    if sc == "never": return False
    if sc == "multicast_fails" and url.startswith("udp://"): return False
    if sc == "needs_hdmi" and hdmi_read() != "connected": return False
    return True
from mock_mpv import MockMpv                                     # tests/mock_mpv.py (also the fake mpv of dev/run-web.sh)
MockMpv(SOCK, state, can_start=can_start, log_lines=[("vo/drm", "mock line 0"), ("vo/drm", "mock line 1"),
        ("vo/drm", "mock line 2 from 192.168.1.20 https://api.tv.init7.net/api/live/?channel=x&sig=abc Bearer eyJ.secret")]).serve()

# --- Start control.py ------------------------------------------------------
PORT = 18765
env = dict(os.environ, TV7_TRANSLATIONS=os.path.join(HERE, "..", "translations"), TV7_DRM_DIR=DRM, TV7_START_TIMEOUT="2", TV7_UI_PORT="18768", TV7_SRG_FHD="false", TV7_VERSION="9.9.9", TV7_HW_AVAILABLE="yes", TV7_MODE_WAIT_S="1", TV7_FAVORITES=f"{tmp}/favorites.json", TV7_LOGO_DIR=f"{tmp}/logos", TV7_LOGO_PREFIX=f"http://127.0.0.1:{api.server_port}/media/logos/", TV7_UI_ALLOW="127.0.0.1", TV7_UI_BIND="127.0.0.1", TV7_OPTIONS=f"{tmp}/options.json", SUPERVISOR_TOKEN="tok", TV7_SUPERVISOR=f"http://127.0.0.1:{sup_srv.server_port}", TV7_MODETEST=f"{tmp}/modetest", TV7_HDMI_OFF_S="600", TV7_EVENTS_S="30", TV7_CEC_GLOB=f"{tmp}/no-cec*", TV7_DIGIT_S="0.4", TV7_MENU_TIMEOUT_S="2.5", TV7_OSD_CACHE=f"{tmp}/osd")
if not LIVE:
    env["TV7_API"] = f"http://127.0.0.1:{api.server_port}/"
    env["TV7_SRG_MC_URL"] = f"http://127.0.0.1:{api.server_port}/srg-mc.m3u"
    env["TV7_SRG_HLS_URL"] = f"http://127.0.0.1:{api.server_port}/srg-hls.m3u"
p = subprocess.Popen([sys.executable, "-I", CONTROL, SOCK, str(PORT)], env=env)
time.sleep(1)

def get(path):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}")
    try:
        r = urllib.request.urlopen(req, timeout=90); return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)

fails = 0
def check(name, cond, detail=""):
    global fails
    fails += (not cond)
    print(("OK  " if cond else "FAIL"), name, detail)

try:
    check("0a /health", get("/health")[0] == 200)
    check("0b the API needs no token (it is only reachable on this device)", get("/channels")[0] == 200)
    listening = [l.split()[1] for l in open("/proc/net/tcp").read().splitlines()[1:] if l.split()[3] == "0A" and l.split()[1].endswith(":%04X" % PORT)]
    check("0c the API listens on 127.0.0.1 only, not on the network", listening == ["0100007F:%04X" % PORT], str(listening))
    c, d = get("/channels")
    check("1 channel list", c == 200 and any(x["name"] == "SRF 1" for x in d) and (LIVE or len(d) == 4), f"{len(d)} channels")
    check("1b hidden channels are missing", all(x["name"] != "Hidden" for x in d))

    state.update(scenario="ok", cable=True, loads=0); hdmi_write("connected")
    c, d = get("/play?channel=SRF%201")
    check("2 start, HDMI ok, multicast", c == 200 and d["source"] == "multicast" and not any("HDMI" in l for l in d["log"]), str(d["log"]))
    check("2b multicast address without '@'", state["loaded"].startswith("udp://233.") and "@" not in state["loaded"], state["loaded"])

    state.update(scenario="ok", cable=True, loads=0); hdmi_write("disconnected")
    c, d = get("/play?channel=SRF%20zwei")
    time.sleep(0.2)
    check("3 HDMI disconnected: the channel starts anyway with a note; sysfs is only read (no 'detect' written, so it stays disconnected)",
          c == 200 and any("no display connected" in l for l in d["log"]) and hdmi_read() == "disconnected", str(d["log"]) + hdmi_read())
    state.update(novideo=True, loads=0); hdmi_write("disconnected"); t = time.time()
    c, d = get("/play?channel=SRF%20zwei")
    check("3c stream received but no display (mpv has no picture output): stops at once with a clear reason, no retries",
          c == 502 and d.get("reason") == "no_display" and state["loads"] == 1 and time.time() - t < 5 and any("no display is connected" in l for l in d["log"]), str(d["log"]))
    state.update(novideo=False)
    state.update(cable=True); hdmi_write("connected")

    state.update(scenario="multicast_fails", loads=0); hdmi_write("connected")
    c, d = get("/play?channel=pk-srf1")
    check("4 multicast never starts -> 2 attempts, then HLS", c == 200 and d["source"] == "hls" and state["loads"] == 3 and not any("reset" in l.lower() for l in d["log"]), str(d["log"]))
    check("4b HLS URL from Init7", state["loaded"].startswith("https://api.tv.init7.net/api/live/"))

    state.update(scenario="never", loads=0)
    c, d = get("/play?channel=SRF%201")
    check("5 nothing starts -> 502 with log", c == 502 and not d["ok"] and len(d["log"]) >= 4, str(d["log"]))

    c, d = get("/play?channel=does-not-exist-xyz"); check("6 unknown channel -> 404", c == 404, str(d))
    c, d = get("/play?channel=http://evil.example/x.m3u8"); check("7 free-form URL -> 404", c == 404, str(d))
    c, d = get("/play?channel=SRF%201&source=rtsp"); check("8 invalid source -> 400", c == 400)
    if not LIVE:
        c, d = get("/play?channel=Evil&source=multicast"); check("9 tampered sources are rejected (non-multicast, foreign HLS host)", c in (404, 502) and "http://evil" not in str(state["loaded"]), str(d))
        c, d = get("/play?channel=Hidden"); check("9b hidden channel -> 404", c == 404)
        c, d = get("/play?channel=SRF"); check("9c ambiguous partial match -> 404", c == 404, str(d))
        c, d = get("/play?channel=info"); check("9d unique partial match", c in (200, 502) and d.get("channel") == "SRF info", str(d.get("channel")))

    state.update(scenario="ok", cable=True); hdmi_write("connected")
    check("10 there is no HDMI reset (the app runs with protection mode on, /sys is read-only)", get("/hdmi/reset")[0] == 404)
    c, d = get("/status"); check("11 /status", c == 200 and "hdmi" in d)
    c, d = get("/volume?v=abc"); check("12 invalid volume -> 400", c == 400, str(d))
    # /events: the status at once, then whenever it changes (not only every TV7_EVENTS_S, here 30 s)
    def events(url, n, during=None):
        """Read n status messages from a server-sent event stream; during() runs after the first one."""
        resp = urllib.request.urlopen(url, timeout=10)
        out, t0 = [], time.time()
        while len(out) < n and time.time() - t0 < 8:
            line = resp.readline().decode()
            if line.startswith("data: "):
                out.append((json.loads(line[6:]), time.time()))
                if len(out) == 1 and during:
                    during()
        resp.close()
        return out, resp.headers.get("Content-Type")
    get("/play?channel=SRF%201")
    ev, ctype = events(f"http://127.0.0.1:{PORT}/events", 2, lambda: threading.Thread(target=get, args=("/stop",)).start())
    check("12b /events: the status at once, then a new one right after a change (stop)", ctype == "text/event-stream" and len(ev) == 2
          and ev[0][0]["playing"] is True and ev[1][0]["playing"] is False and ev[1][1] - ev[0][1] < 3, str([e[0]["playing"] for e in ev]))
    ev, ctype = events("http://127.0.0.1:18768/events", 1)
    check("12c /events also through the web UI (Ingress)", ctype == "text/event-stream" and len(ev) == 1 and "playing" in ev[0][0])
    # Explicit sources: source=multicast never falls back to HLS, source=hls never tries multicast
    state.update(scenario="multicast_fails", loads=0, cable=True); hdmi_write("connected")
    c, d = get("/play?channel=SRF%201&source=multicast")
    check("16 source=multicast: a multicast failure is final (502, no HLS)", c == 502 and not any(x.startswith("hls") for x in d["log"]), str(d["log"]))
    state.update(scenario="multicast_fails", loads=0)
    c, d = get("/play?channel=SRF%201&source=hls")
    check("17 source=hls uses only HLS", c == 200 and d["source"] == "hls" and state["loaded"].startswith("https://api.tv.init7.net/"), str(d))
    c, d = get("/play?channel=SRF%201&source=auto")
    check("17b source=auto: multicast first, then HLS", c == 200 and d["source"] == "hls" and any(x.startswith("multicast") for x in d["log"]), str(d["log"]))
    state.update(scenario="ok")

    # Deinterlacing only for software-decoded video (the filter would disable hardware decoding)
    state.update(scenario="ok", cable=True, loads=0, hw=False, deint=None); hdmi_write("connected")
    get("/play?channel=SRF%201"); check("40 software decoding -> deinterlace auto (only interlaced frames; option default)", state["deint"] == "auto", str(state["deint"]))
    state.update(hw=True, deint=None); get("/play?channel=SRF%201"); check("40b hardware decoding -> deinterlace off", state["deint"] is False, str(state["deint"]))
    state.update(hw=False)
    # Output refresh rate follows the stream: stream 50 fps, display preferred 3840x2160@60, a 50 Hz mode (index 1) is offered
    open(f"{tmp}/options-auto.json", "w").write(json.dumps({"video_refresh": "auto", "video_mode": "auto"}))
    p6 = subprocess.Popen([sys.executable, "-I", CONTROL, SOCK, "18773"], env=dict(env, TV7_OPTIONS=f"{tmp}/options-auto.json", TV7_UI_PORT="0", TV7_SRG_FHD="false"))
    time.sleep(1)
    try:
        def get6(path):
            try:
                r = urllib.request.urlopen(f"http://127.0.0.1:18773{path}", timeout=60); return r.status, json.load(r)
            except urllib.error.HTTPError as e:
                return e.code, json.load(e)
        override = lambda port=18773: json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/nerd", timeout=30))["output"]["drm_mode_override"]
        state.update(scenario="ok", cable=True, loads=0, quit=0, hw=False, fps=50.0); hdmi_write("connected")
        c, d = get6("/play?channel=SRF%201")
        check("44 video_refresh=auto: mpv starts at 1080p50, so a 50 fps stream needs no switch", c == 200 and state["quit"] == 0 and override() is None, str(d["log"]))
        state.update(fps=59.94, loads=0)
        c, d = get6("/play?channel=SRF%201")
        check("44b a 60 fps stream switches the display to 1080p59.94 (index 4) and plays again",
              c == 200 and override() == "4" and state["quit"] == 1 and state["loads"] == 2 and any("follows the stream" in x for x in d["log"]), str(d["log"]) + str(state["quit"]))
        c, d = get6("/play?channel=SRF%201")
        check("44c the same frame rate again: no further restart", c == 200 and state["quit"] == 1, str(state["quit"]))
        state.update(fps=50.0); c, d = get6("/play?channel=SRF%201")
        check("44d back to a 50 fps stream: 1080p50 again (index 3)", c == 200 and override() == "3" and state["quit"] == 2, str(state["quit"]))
    finally:
        p6.terminate()
    # mpv was started without a display ("preferred" = 4K60 here); that start mode is known, so a 50 fps stream still switches
    p6b = subprocess.Popen([sys.executable, "-I", CONTROL, SOCK, "18772"], env=dict(env, TV7_OPTIONS=f"{tmp}/options-auto.json", TV7_UI_PORT="0",
                           TV7_SRG_FHD="false", TV7_VIDEO="vo=gpu pending=no hw=no mode=preferred"))
    time.sleep(1)
    try:
        state.update(quit=0, fps=50.0)
        r = urllib.request.urlopen("http://127.0.0.1:18772/play?channel=SRF%201", timeout=60); d = json.load(r)
        check("44e started with the display's preferred mode (60 Hz): a 50 fps stream switches to 1080p50", override(18772) == "3" and state["quit"] == 1, str(d["log"]))
    finally:
        p6b.terminate()
    # Web UI (Ingress): served on its own port, only for allowed addresses, no token needed there
    def ui(path, port=18768):
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=30); return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
    c, body = ui("/"); check("18 UI page is served without token", c == 200 and "<title>TV7 Player</title>" in body)
    r = urllib.request.urlopen("http://127.0.0.1:18768/logo.png", timeout=30); check("18b UI serves the logo", r.status == 200 and r.read(4) == b"\x89PNG")
    c, body = ui("/status"); check("19 UI port serves the API without token", c == 200 and "hdmi" in json.loads(body))
    c, body = ui("/environment"); e = json.loads(body)
    check("20 /environment: HDMI ports, audio devices, choices, no token leak",
          c == 200 and e["hdmi_ports"][0]["name"] == "HDMI-A-1" and "1920x1080" in e["hdmi_ports"][0]["modes"] and len(e["hdmi_ports"][0]["modes"]) == 3
          and any(d["name"].startswith("pulse/") for d in e["audio"]["devices"]) and "HDMI-A-1" in e["choices"]["hdmi_port"]
          and "secret" not in body, str(e)[:300])
    c, body = ui("/volume?d=-5"); check("21 relative volume", c == 200)
    c, body = ui("/mute"); check("22 mute toggle", c == 200)
    c, d = get("/status"); check("23 /status has channel and mute fields", "channel" in d and "mute" in d and "pk" in d, str(d))
    p3 = subprocess.Popen([sys.executable, "-I", CONTROL, SOCK, "18769"], env=dict(env, TV7_UI_PORT="18770", TV7_UI_ALLOW="172.30.32.2"))
    time.sleep(1)
    try:
        c, body = ui("/", 18770); check("24 UI refuses other addresses than the Supervisor (403)", c == 403)
        c, body = ui("/status", 18770); check("24b UI port does not serve the API to others", c == 403)
    finally:
        p3.terminate()
    # CPU load, tracks and track switching
    c, d = get("/status")
    c, d = get("/status"); check("25a /status reports the render path and hardware decoding", d["vo"] == "drm" and d["hwdec"] in ("no", "drm"), str((d.get("vo"), d.get("hwdec"))))
    c, d = get("/status"); check("25b /status reports the app version (the page reloads itself after an update)", d.get("version") == "9.9.9", str(d.get("version")))
    check("25 /status: system load, tracks, pending_restart", "cores" in d["system"] and len(d["audio_tracks"]) == 2 and d["sub_tracks"][0]["lang"] == "deu" and d["pending_restart"] == [], str(d)[:300])
    # Nerd mode: every technical detail in one read-only call, plus an excerpt of the mpv log
    c, d = get("/nerd")
    check("46 /nerd: codec, bitrate, dropped frames, DRM device/planes, system", c == 200 and d["video"]["codec"] == "h264" and d["video"]["bitrate"] == 6400000
          and d["frames"]["dropped_vo"] == 3 and d["frames"]["dropped_decoder"] == 1 and d["output"]["drm_device"] == "/dev/dri/card1"
          and d["output"]["draw_plane"] == "overlay" and d["output"]["video_plane"] == "primary" and d["audio"]["samplerate"] == 48000
          and "clock" in d["system"] and "memory" in d["system"] and isinstance(d["log"], list), str(d)[:400])
    time.sleep(0.6); c, d = get("/nerd")
    check("46b /nerd collects mpv log messages (request_log_messages)", any("[vo/drm] info: mock line 2" in x for x in d["log"]) and state.get("log_requests", 0) >= 1, str(d["log"]))
    c, d = get("/support"); t = d.get("text", "")
    check("48 /support: Markdown in the issue template layout with versions, playback, output, environment, options, log",
          c == 200 and all(h in t for h in ("## Problem/Motivation", "## Steps to reproduce", "## System", "## Playback", "## Display output", "## Environment", "## Options", "<details>"))
          and "| TV7 Player | 9.9.9 |" in t and "HDMI-A-1" in t and "/dev/dri/card1" in t and "mock line 2" in t, t[:300])
    check("48b /support masks secrets: bearer tokens, URL parameters, unicast IPs, options of older versions; keeps multicast addresses",
          "secret-should-not-show" not in t and "api_token" not in t and "eyJ.secret" not in t and "sig=abc" not in t
          and "192.168.1.20" not in t and "udp://233.50.230.80:5000" in t, [l for l in t.splitlines() if "mock line 2" in l or "api_token" in l])
    check("48e /support has the last channel start with its log, the channel list sync state and pending restarts",
          "## Last channel start" in t and "multicast: started" in t and "| TV7 channels | 4 |" in t and "Last successful sync" in t
          and "waiting for a restart: none" in t and "Report created" in t, t[t.find("## Last channel start"):][:600])
    check("48d /support has HAOS/Core versions, machine and the app log from the Supervisor (colour codes removed, masked)",
          "| Home Assistant OS | 16.3 |" in t and "| Home Assistant Core | 2026.11.2 |" in t and "raspberrypi5-64 / aarch64" in t
          and ">>> Video output (auto): gpu" in t and "\x1b" not in t and "10.1.2.3" not in t and "token=abc" not in t and sup.get("range", "").startswith("entries="), t[-500:])
    c, body = ui("/nerd"); check("46d /nerd on the web UI port", c == 200 and "log" in json.loads(body))
    c, body = ui("/"); check("46e UI page has the nerd mode switch (off by default)", 'id="nerd-toggle" aria-pressed="false"' in body and 'id="nerd-card" hidden' in body)
    c, d = get("/track?type=audio&id=2"); check("26 switch audio track", c == 200)
    c, d = get("/track?type=sub&id=off"); check("26b subtitles off", c == 200)
    get("/track?type=sub&id=1"); c, d = get("/play?channel=SRF%201")
    check("26e every channel starts without subtitles, even after a subtitle track was chosen", c == 200 and state.get("sid") == "no", str(state.get("sid")))
    c, d = get("/osd?on=1&lang=de"); time.sleep(0.3)
    last = (state.get("osd") or [{}])[-1]
    check("55 TV info on: osd-overlay with the channel and German labels", c == 200 and d["on"] is True and last.get("name") == "osd-overlay"
          and last.get("format") == "ass-events" and "SRF 1" in last.get("data", "") and "Ausgabe" in last.get("data", ""), str(last)[:300])
    check("55b /status reports the TV info as on", get("/status")[1].get("osd") is True)
    n = len(state["osd"]); time.sleep(1.5)
    check("55c the overlay is refreshed while on", len(state["osd"]) > n, str(len(state["osd"]) - n))
    check("55d invalid value -> 400", get("/osd?on=yes")[0] == 400)
    get("/stop"); time.sleep(1.5)
    check("55e nothing playing: the overlay is removed (idle logo stays clean)", state["osd"][-1].get("format") == "none", str(state["osd"][-1]))
    get("/play?channel=SRF%201"); time.sleep(1.5)
    check("55f a channel starts again: the overlay comes back", state["osd"][-1].get("format") == "ass-events", str(state["osd"][-1])[:100])
    c, d = get("/osd?on=0")
    check("55g TV info off: overlay removed, /status reports off", c == 200 and d["on"] is False and state["osd"][-1].get("format") == "none" and get("/status")[1].get("osd") is False)
    # TV menu (remote control keys over CEC or /key): OSD overlays id 8 (menu) and 9 (banner)
    def osd_last(i):
        return next((o for o in reversed(state.get("osd", [])) if o.get("id") == i), {})
    c, d = get("/key?k=ok"); m = osd_last(8)
    check("57 OK opens the menu: channels tab, lists with the running channel, translucent panel", c == 200 and d["menu"] is True and d["tab"] == "channels"
          and m.get("format") == "ass-events" and "SRF 1" in m["data"] and "SRF zwei" in m["data"] and r"\blur" in m["data"] and m.get("res_x") == 1920, str(d) + str(m)[:200])
    before = state["loaded"]
    get("/key?k=down"); c, d = get("/key?k=ok")
    for _ in range(30):
        if state["loaded"] != before and osd_last(9).get("format") == "ass-events": break
        time.sleep(0.1)
    check("57t without nerd mode no channel numbers on the TV (menu list, banner)", "1102" not in m.get("data", "") and "1104" not in osd_last(9).get("data", ""),
          osd_last(9).get("data", "")[-160:])
    check("57b down + OK plays the next channel, closes the menu and shows the channel banner", d["menu"] is False and state["loaded"] != before
          and osd_last(8).get("format") == "none" and osd_last(9).get("format") == "ass-events", str(d) + str(state["loaded"]))
    banner_text = osd_last(9).get("data", "")
    check("57v the channel banner after a start: name and source, no channel number (nerd mode off)", "SRF" in banner_text
          and not any(n in banner_text for n in ("1102", "1104", "1106")), banner_text[-200:])
    time.sleep(2.5)
    get("/key?k=ok"); c, d = get("/key?k=right"); m = osd_last(8)
    check("57c right switches to the audio tab with the stream's tracks", d["tab"] == "audio" and "Deutsch" in m.get("data", ""), str(d) + m.get("data", "")[-300:])
    state.pop("aid", None); get("/key?k=ok")
    check("57d OK on an audio track selects it", state.get("aid") == 1, str(state.get("aid")))
    c, d = get("/key?k=left"); c, d = get("/key?k=back")
    check("57e back closes the menu", d["menu"] is False and osd_last(8).get("format") == "none", str(d))
    before = state["loaded"]; get("/key?k=ch_up")
    for _ in range(30):
        if state["loaded"] != before: break
        time.sleep(0.1)
    check("57f channel up zaps to the next channel of the list", state["loaded"] != before, str(state["loaded"]))
    for k in "1104":
        get("/key?k=" + k)
    check("57g digits show the number in the banner", "1104_" in osd_last(9).get("data", ""), osd_last(9).get("data", "")[-200:])
    for _ in range(40):
        if str(state["loaded"]).startswith("udp://233.50.230.212"): break
        time.sleep(0.1)
    check("57h after the pause the channel number is played (1104 = SRF zwei)", str(state["loaded"]).startswith("udp://233.50.230.212"), str(state["loaded"]))
    get("/key?k=ok"); time.sleep(4.5)
    check("57i the menu closes by itself without a key", osd_last(8).get("format") == "none", str(osd_last(8))[:100])
    check("57j unknown key -> 400", get("/key?k=power")[0] == 400)
    # Settings tab: OK switches a setting to its next value and saves it like the web UI; technical ones only in nerd mode
    get("/key?k=ok"); c, d = get("/key?k=left"); m = osd_last(8).get("data", "")
    check("57l left from the channels tab: the settings tab with the settings, technical ones hidden", d["tab"] == "settings"
          and "HDMI port" in m and "Video output" not in m and osd_last(10).get("format") == "ass-events", m[-300:])
    for _ in range(15):
        get("/key?k=down")                                        # the last entry: nerd mode (after stop and the technical info)
    m = osd_last(8).get("data", "")
    check("57q the technical info and nerd mode are the last entries of the settings tab", m.rfind("Technical info on the TV") < m.rfind("Nerd mode")
          and m.rfind("Stop playback") < m.rfind("Technical info on the TV"), m[-400:])
    get("/key?k=ok"); m = osd_last(8).get("data", "")
    check("57r nerd mode switched on: the selection stays on 'Nerd mode' (more settings appear above it)",
          re.search(r"\\b1[^}]*\}Nerd mode", m) is not None and "PICTURE AND HDMI" not in m.split("Nerd mode")[-1], m[-400:])
    check("57s settings grouped like the web UI, the TV entries in their own group", all(g in m or g in osd_last(8).get("data", "") for g in ("SYSTEM", "DISPLAY")), m[-300:])
    for _ in range(25):
        get("/key?k=up")
    m = osd_last(8).get("data", "")
    check("57m nerd mode in the TV menu shows the technical settings too", "Video output" in m, m[-300:])
    get("/key?k=ok"); m = osd_last(8).get("data", "")
    check("57n OK on a setting saves its next value through the Supervisor and offers the restart", (sup["options"] or {}).get("hdmi_port") == "HDMI-A-1"
          and "HDMI-A-1 · restart" in m, str(sup["options"]) + m[-300:])
    for _ in range(3):                                            # back to auto through the menu (HDMI-A-1 -> HDMI-A-2 -> auto)
        if (sup["options"] or {}).get("hdmi_port") == "auto": break
        get("/key?k=ok")
    c, d = get("/key?k=right"); m = osd_last(8).get("data", "")
    check("57u nerd mode on: the channel list shows the channel numbers", d["tab"] == "channels" and "1102" in m and "1104" in m, m[-200:])
    get("/key?k=left")
    check("57p OK cycles through the values back to the start", (sup["options"] or {}).get("hdmi_port") == "auto", str(sup["options"]))
    get("/key?k=back")
    check("57o back closes the menu with its background", osd_last(8).get("format") == "none" and osd_last(10).get("format") == "none")
    c, body = ui("/"); check("57k web UI without remote pad (the TV menu is operated with the TV remote)", 'id="remote"' not in body and 'data-k="ok"' not in body)
    planes_txt = "Planes:\nid\tcrtc\tfb\tCRTC x,y\tx,y\tgamma size\tpossible crtcs\n32\t0\t0\t0,0\t\t0,0\t0\t0x1\n  props:\n\t8 type:\n\t\tenums: Overlay=0 Primary=1 Cursor=2\n\t\tvalue: 1\n" \
                 "40\t71\t88\t0,0\t\t0,0\t0\t0x1\n  props:\n\t8 type:\n\t\tenums: Overlay=0 Primary=1 Cursor=2\n\t\tvalue: 0\n\t38 alpha:\n\t\tvalues: 0 65535\n\t\tvalue: 65535\n" \
                 "\t39 pixel blend mode:\n\t\tenums: None=2 Pre-multiplied=0 Coverage=1\n\t\tvalue: 1\n\t41 zpos:\n\t\tvalue: 2\n"
    r = subprocess.run([sys.executable, "-c", "import sys, json; sys.path.insert(0, sys.argv[1]); from tv7 import display; print(json.dumps(display.parse_planes(sys.argv[2])))",
                        os.path.dirname(CONTROL), planes_txt], capture_output=True, text=True, timeout=30)
    pl = json.loads(r.stdout or "[]")
    fix_txt = "Planes:\nid\tcrtc\tfb\tCRTC x,y\tx,y\tgamma size\tpossible crtcs\n83\t71\t90\t0,0\t\t0,0\t0\t0x1\n  props:\n\t8 type:\n\t\tenums: Overlay=0 Primary=1 Cursor=2\n\t\tvalue: 1\n" \
              "\t38 alpha:\n\t\tvalues: 0 65535\n\t\tvalue: 65535\n" \
              "107\t71\t91\t0,0\t\t0,0\t0\t0x1\n  props:\n\t8 type:\n\t\tenums: Overlay=0 Primary=1 Cursor=2\n\t\tvalue: 0\n\t38 alpha:\n\t\tvalues: 0 65535\n\t\tvalue: 3084\n" \
              "\t39 pixel blend mode:\n\t\tenums: None=2 Pre-multiplied=0 Coverage=1\n\t\tvalue: 1\n" \
              "108\t0\t0\t0,0\t\t0,0\t0\t0x1\n  props:\n\t8 type:\n\t\tenums: Overlay=0 Primary=1 Cursor=2\n\t\tvalue: 0\n\t38 alpha:\n\t\tvalue: 65535\n" \
              "\t39 pixel blend mode:\n\t\tenums: None=2 Pre-multiplied=0 Coverage=1\n\t\tvalue: 0\n"
    r = subprocess.run([sys.executable, "-c", "import sys, json; sys.path.insert(0, sys.argv[1]); from tv7 import display; print(json.dumps(display.plane_fixes(sys.argv[2])))",
                        os.path.dirname(CONTROL), fix_txt], capture_output=True, text=True, timeout=30)
    check("58b overlay plane left at alpha 3084 / Coverage (seen on the Pi 5): set to opaque and pre-multiplied; primary and correct planes untouched",
          json.loads(r.stdout or "[]") == ["107:alpha:65535", "107:pixel blend mode:0"], r.stdout + r.stderr)
    check("58 DRM planes (nerd/support): only planes with a picture, with type, alpha, blend mode, zpos",
          pl == [{"id": 40, "crtc": 71, "fb": 88, "type": "Overlay", "alpha": "65535", "pixel blend mode": "Coverage", "zpos": "2"}], r.stdout + r.stderr)
    c, body = ui("/"); check("55h web UI without the TV info switch (switched in the TV menu or with /osd)", 'osd-field' not in body and 'id="osd-on"' not in body)
    c, d = get("/track?type=video&id=1"); check("26c invalid track type -> 400", c == 400)
    c, d = get("/track?type=audio&id=abc"); check("26d invalid track id -> 400", c == 400)

    # Idle screen: the logo PNG becomes premultiplied BGRA for mpv's overlay-add (prepared before mpv starts)
    logo = os.path.join(HERE, "..", "rootfs", "ui-logo.png")
    IDLE = ("import sys; sys.path.insert(0, sys.argv[1]); from tv7 import display\n"
            "w, h, px = display.png_to_bgra(sys.argv[2]); open(sys.argv[3], 'wb').write(px); print(w, h)")
    r = subprocess.run([sys.executable, "-c", IDLE, os.path.dirname(CONTROL), logo, f"{tmp}/idle.bgra"], capture_output=True, text=True, timeout=30)
    raw = open(f"{tmp}/idle.bgra", "rb").read() if r.returncode == 0 else b""
    px = [raw[i:i + 4] for i in range(0, len(raw), 4)]
    check("54 idle logo: size printed, raw BGRA of that size", r.stdout.split() == ["360", "188"] and len(raw) == 360 * 188 * 4, r.stdout + r.stderr)
    check("54b idle logo: transparent corner, opaque logo colour, premultiplied alpha everywhere",
          px[0] == b"\0\0\0\0" and any(p[3] == 255 and p[2] > 200 and p[0] < 150 for p in px) and all(max(p[:3]) <= p[3] for p in px), str(px[0]))
    bad = subprocess.run([sys.executable, "-c", IDLE, os.path.dirname(CONTROL), os.path.join(HERE, "..", "config.yaml"), f"{tmp}/x.bgra"], capture_output=True, text=True, timeout=30)
    check("54c idle logo: a file that is not a PNG fails (the screen then stays black)", bad.returncode != 0)
    big = subprocess.run([sys.executable, "-c", "import sys, struct, zlib; sys.path.insert(0, sys.argv[1]); from tv7 import display\n"
                          "ch = lambda k, d: struct.pack('>I', len(d)) + k + d + struct.pack('>I', zlib.crc32(k + d))\n"
                          "png = b'\\x89PNG\\r\\n\\x1a\\n' + ch(b'IHDR', struct.pack('>IIBBBBB', 20000, 20000, 8, 6, 0, 0, 0)) + ch(b'IDAT', zlib.compress(bytes(1000000))) + ch(b'IEND', b'')\n"
                          "try:\n    display.png_bytes_to_bgra(png); print('decoded')\nexcept ValueError as e:\n    print('refused', e)",
                          os.path.dirname(CONTROL)], capture_output=True, text=True, timeout=30)
    check("54d PNG decoder refuses huge images (no memory/CPU exhaustion through a logo)", big.stdout.startswith("refused"), big.stdout + big.stderr)
    cons = subprocess.run([sys.executable, "-c", """
import sys, re, yaml
sys.path.insert(0, sys.argv[1]); from tv7 import settings as c
cfg = yaml.safe_load(open(sys.argv[2])); opts, schema = cfg["options"], cfg["schema"]
bad = []
for s in c.SETTINGS:
    k = s["key"]
    if k not in opts or str(opts[k]) != str(c.DEFAULTS.get(k)): bad.append(f"default {k}")
    if s["type"] == "choice" and str(schema.get(k)) != "list(" + "|".join(s["choices"]) + ")": bad.append(f"choices {k}")
for lg in ("en", "de", "fr", "it"):
    t = yaml.safe_load(open(f"{sys.argv[3]}/{lg}.yaml"))["configuration"]
    bad += [f"{lg}: {k}" for k in set(opts) ^ set(t)]
print(bad or "ok")
""", os.path.dirname(CONTROL), os.path.join(HERE, "..", "config.yaml"), os.path.join(HERE, "..", "translations")], capture_output=True, text=True, timeout=30)
    check("59 settings agree: config.yaml options/schema, the web UI's settings and defaults, all four translations", cons.stdout.strip() == "ok", cons.stdout + cons.stderr)
    c, body = ui("/")
    check("60 the web UI gets its texts from i18n/<lang>.json, all four languages, no placeholder left",
          c == 200 and "/*I18N*/" not in body and '"favTitle": "Favoriten"' in body and '"favTitle": "Favoris"' in body and '"favTitle": "Preferiti"' in body, body[:0])
    texts = {lg: json.load(open(os.path.join(HERE, "..", "rootfs", "i18n", f"{lg}.json"), encoding="utf-8")) for lg in ("en", "de", "fr", "it")}
    diff = {lg: sorted(set(texts[lg][part]) ^ set(texts["en"][part])) for lg in texts for part in ("ui", "tv") if set(texts[lg][part]) != set(texts["en"][part])}
    check("60b every language has every text (web UI and TV)", not diff, str(diff))

    # Output mode resolution (fake modetest): presets resolve to a mode index; unavailable ones fall back to preferred
    def resolve(mode, hz, port="", modetest=f"{tmp}/modetest"):
        r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); from tv7 import display\n"
                            "mode, note = display.resolve_mode(*sys.argv[2:5]); print(mode); print(note or '', file=sys.stderr)",
                            os.path.dirname(CONTROL), mode, hz, port], env=dict(env, TV7_MODETEST=modetest), capture_output=True, text=True, timeout=20)
        return r.stdout.strip(), r.stderr.strip()
    check("27 1080p/50 -> index of the progressive 50 Hz mode (not the interlaced one)", resolve("1080p", "50", "HDMI-A-1")[0] == "3", str(resolve("1080p", "50")))
    check("27b 1080p/60 -> 59.94 Hz mode", resolve("1080p", "60")[0] == "4")
    check("27c 2160p/50 -> index 1", resolve("2160p", "50")[0] == "1")
    check("27d 720p (not offered) -> preferred, with a reason", resolve("720p", "50")[0] == "preferred" and "not offered" in resolve("720p", "50")[1])
    check("27e auto means 1080p when the display offers it, starting at 50 Hz (or at the asked 50/60 Hz); highest passes through",
          resolve("auto", "auto")[0] == "3" and resolve("auto", "50")[0] == "3" and resolve("auto", "60")[0] == "4" and resolve("highest", "50")[0] == "highest",
          str((resolve("auto", "auto"), resolve("auto", "50"), resolve("auto", "60"))))
    open(f"{tmp}/modetest2.txt", "w").write(MODETEST_OUT.replace("1920x1080 ", "1680x1050 "))
    open(f"{tmp}/modetest2", "w").write(f"#!/bin/sh\ncat {tmp}/modetest2.txt\n"); os.chmod(f"{tmp}/modetest2", 0o755)
    check("27h a fixed resolution with the rate following the stream starts at 50 Hz", resolve("1080p", "auto")[0] == "3" and resolve("2160p", "auto")[0] == "1")
    check("27g auto on a display without 1080p: its preferred size at 50 Hz (or at the asked rate)",
          resolve("auto", "auto", "", f"{tmp}/modetest2")[0] == "1" and resolve("auto", "50", "", f"{tmp}/modetest2")[0] == "1",
          str((resolve("auto", "auto", "", f"{tmp}/modetest2"), resolve("auto", "50", "", f"{tmp}/modetest2"))))
    check("27f unknown port -> preferred", resolve("1080p", "50", "HDMI-A-9")[0] == "preferred")

    # Settings: choices, labels, validation, saving through the Supervisor, live apply, pending-restart flag
    c, body = ui("/settings?lang=de"); S = json.loads(body)
    keys = [i["key"] for i in S["items"]]
    check("28 /settings: items, German labels, restart flags, can_save", c == 200 and "video_mode" in keys and S["labels"]["video_mode"]["name"] == "Bildauflösung"
          and next(i for i in S["items"] if i["key"] == "video_mode")["restart"] is True and S["can_save"] is True and "api_token" not in keys, str(S)[:200])
    it = {i["key"]: i for i in S["items"]}
    check("28c technical settings are flagged for nerd mode; the everyday ones are not",
          all(it[k]["nerd"] for k in ("video_mode", "hardware_decoding", "audio_device", "debug"))
          and not any(it[k]["nerd"] for k in ("hdmi_port", "hdmi_disconnect", "audio_language", "start_volume", "audio_channels", "idle_stop")), str({k: v["nerd"] for k, v in it.items()}))
    check("28b live choices: 720p is not offered by the display, 2160p/1080p are", "720p" in it["video_mode"]["unavailable"]
          and "2160p" not in it["video_mode"]["unavailable"] and "1080p" not in it["video_mode"]["unavailable"], str(it["video_mode"]["unavailable"]))
    def post(path, body, headers=None, port=18768):
        h = {"Content-Type": "application/json", "X-TV7-UI": "1", **(headers or {})}
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), headers=h, method="POST")
        try:
            r = urllib.request.urlopen(req, timeout=30); return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)
    check("29 POST without the X-TV7-UI header -> 403", post("/settings", {"values": {}}, {"X-TV7-UI": "0"})[0] == 403)
    check("29b invalid value -> 400", post("/settings", {"values": {"video_mode": "8k"}})[0] == 400)
    check("29c option that does not exist (any more) -> 400", post("/settings", {"values": {"listen": "0.0.0.0"}})[0] == 400)
    check("29d wrong type -> 400", post("/settings", {"values": {"start_volume": "loud"}})[0] == 400)
    c, d = post("/settings", {"values": {"video_mode": "2160p", "audio_channels": "stereo", "audio_language": "fra", "start_volume": 90}})
    check("30 save: stored via Supervisor with merged options, options of older versions dropped", c == 200 and sup["options"]["video_mode"] == "2160p" and "api_token" not in sup["options"]
          and sup["auth"] == "Bearer tok" and "subtitles" not in sup["options"], str(sup["options"]))
    check("30b restart-only setting is pending, live ones are applied now", d["pending_restart"] == ["video_mode"] and set(d["applied_now"]) == {"audio_channels", "audio_language", "start_volume"}, str(d))
    c, d = get("/status"); check("30c /status shows the pending-restart flag", d["pending_restart"] == ["video_mode"], str(d["pending_restart"]))
    post("/settings", {"values": {"audio_channels": "auto", "video_mode": "auto", "start_volume": 100, "audio_language": "auto"}})
    c, d = get("/status"); check("30e setting the old value again clears the flag", d["pending_restart"] == [], str(d["pending_restart"]))
    sup["reject"] = True
    c, d = post("/settings", {"values": {"deinterlace": False}}); check("31 Supervisor rejection is reported (502)", c == 502 and "invalid option" in d["error"], str(d))
    sup["reject"] = False
    c, d = post("/restart", {}); time.sleep(1.2); check("32 restart request reaches the Supervisor", c == 200 and sup["restarts"] == 1, str(sup))
    c, body = ui("/settings"); check("33 /settings is not served on the API port", urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/settings")).status == 200)
    # SRG Full HD as a separate list (second instance with srg_fhd on)
    P4 = 18771
    p4 = subprocess.Popen([sys.executable, "-I", CONTROL, SOCK, str(P4)], env=dict(env, TV7_SRG_FHD="true", TV7_UI_PORT="0", TV7_HDMI_POLL_S="0.3"))
    time.sleep(1)
    try:
        def get4(path):
            try:
                r = urllib.request.urlopen(f"http://127.0.0.1:{P4}{path}", timeout=60); return r.status, json.load(r)
            except urllib.error.HTTPError as e:
                return e.code, json.load(e)
        c, d = get4("/channels")
        srg = [x for x in d if x["list"] == "srg_fhd"]
        check("34 SRG Full HD is a separate list next to TV7", c == 200 and [x["name"] for x in srg] == ["SRF 1 FHD", "RTS 1 FHD"] and any(x["list"] == "tv7" for x in d), str(d)[:300])
        state.update(scenario="ok", cable=True, loads=0); hdmi_write("connected")
        c, d = get4("/play?channel=SRF%201%20FHD&source=hls")
        check("35 SRG HLS URL on vtvapi03.sys.init7.net is accepted", c == 200 and state["loaded"].startswith("https://vtvapi03.sys.init7.net/"), str(d))
        c, d = get4("/play?channel=SRF%201%20FHD&source=multicast")
        check("35b SRG multicast URL", c == 200 and state["loaded"] == "udp://233.50.230.1:5000?fifo_size=65536&overrun_nonfatal=1", state["loaded"])
        c, d = get4("/play?channel=RTS%201%20FHD&source=hls")
        check("35c SRG HLS entry from a foreign host is rejected", c in (404, 502) and "evil" not in str(state["loaded"]), str(d))
        c, d = get4("/play?channel=SRF%201"); check("35d exact name 'SRF 1' still means the TV7 channel", c == 200 and d["channel"] == "SRF 1", str(d))
        # One mpv configuration: switching between a TV7 channel (software) and an SRG Full HD channel (H.265 in hardware) needs no restart
        state.update(scenario="ok", cable=True, loads=0, quit=0, hw=False)
        get4("/play?channel=SRF%201"); c, d = get4("/play?channel=SRF%201%20FHD"); get4("/play?channel=SRF%201"); get4("/stop")
        check("43 TV7 and SRG Full HD channels alternate without restarting mpv", c == 200 and state["quit"] == 0, str(d.get("log")))
    finally:
        p4.terminate()
    # Video output chosen without a display (TV off when the app started): chosen again once a display is connected
    p4b = subprocess.Popen([sys.executable, "-I", CONTROL, SOCK, "18784"], env=dict(env, TV7_UI_PORT="0", TV7_VIDEO="vo=drm pending=yes hw=no"))
    time.sleep(1)
    try:
        def get4b(path):
            try:
                r = urllib.request.urlopen(f"http://127.0.0.1:18784{path}", timeout=60); return r.status, json.load(r)
            except urllib.error.HTTPError as e:
                return e.code, json.load(e)
        state.update(quit=0, cable=False); hdmi_write("disconnected")
        c, d = get4b("/play?channel=SRF%201"); check("53 pending video output, still no display: no restart", state["quit"] == 0, str(d.get("log")))
        state.update(cable=True); hdmi_write("connected"); c, d = get4b("/play?channel=SRF%201")
        check("53b pending video output, display connected: mpv restarts once so the output is chosen again", state["quit"] == 1
              and any("choosing the video output again" in x for x in d["log"]), str(d.get("log")))
    finally:
        p4b.terminate()
    c, d = get("/channels"); check("36 srg_fhd=false: no SRG channels", all(x["list"] == "tv7" for x in d))
    # Channel logos (served and cached by the app, only from Init7 logo URLs) and the app version
    c, ch = get("/channels"); logo = ch[0]["logo"]
    r = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/icon?u={urllib.parse.quote(logo, safe='')}"), timeout=30)
    check("38 /channels lists logos and /icon serves them as PNG", logo.endswith(".png") and r.status == 200 and r.read(4) == b"\x89PNG" and r.headers["Cache-Control"].startswith("public"))
    c, d = get("/icon?u=http%3A%2F%2Fevil.example%2Fx.png"); check("38b /icon refuses URLs outside the Init7 logo prefixes (403)", c == 403, str(d))
    c, d = get("/icon?u=" + urllib.parse.quote(logo.rsplit(".", 1)[0] + ".svg", safe="")); check("38c /icon only accepts PNG/JPEG (403)", c == 403)
    import os as _os
    check("38d the logo is cached on disk", hashlib.sha256(logo.encode()).hexdigest() in _os.listdir(f"{tmp}/logos"))
    c, body = ui("/settings"); check("39 /settings reports the app version", json.loads(body)["version"] == "9.9.9")
    # Favorites (shared by all users of the web UI) and the resolution/refresh rate shown in the player
    c, d = get("/status"); check("41 /status reports stream and output resolution", d["stream"] == {"w": 1280, "h": 720, "fps": 50.0} and d["output"] == {"w": 1920, "h": 1080, "hz": 50.0}, str(d["stream"]) + str(d["output"]))
    c, body = ui("/favorites"); check("42 no favorites yet", json.loads(body)["favorites"] == [])
    c, d = post("/favorites", {"favorites": ["pk-srf1", "srg-fhd:SRF 1 FHD", "pk-srf1"]}); check("42b save favorites (de-duplicated, order kept)", c == 200 and d["favorites"] == ["pk-srf1", "srg-fhd:SRF 1 FHD"], str(d))
    c, body = ui("/favorites"); check("42c favorites persist", json.loads(body)["favorites"] == ["pk-srf1", "srg-fhd:SRF 1 FHD"])
    check("42d invalid favorites -> 400", post("/favorites", {"favorites": "SRF 1"})[0] == 400 and post("/favorites", {"favorites": [1, 2]})[0] == 400)
    check("42e saving favorites needs the X-TV7-UI header (403)", post("/favorites", {"favorites": []}, {"X-TV7-UI": "0"})[0] == 403)
    post("/favorites", {"favorites": []})
    # Live reload for development: with TV7_DEV_RELOAD the reported version changes when the UI file changes (the page then reloads itself)
    open(f"{tmp}/ui.html", "w").write("<title>TV7 Player</title>")
    p7 = subprocess.Popen([sys.executable, "-I", CONTROL, SOCK, "18774"], env=dict(env, TV7_DEV_RELOAD="1", TV7_UI_FILE=f"{tmp}/ui.html", TV7_UI_PORT="0"))
    time.sleep(1)
    try:
        v1 = json.load(urllib.request.urlopen("http://127.0.0.1:18774/status", timeout=30))["version"]
        t = time.time() + 5; os.utime(f"{tmp}/ui.html", (t, t))
        v2 = json.load(urllib.request.urlopen("http://127.0.0.1:18774/status", timeout=30))["version"]
        check("47 TV7_DEV_RELOAD: the version changes after the UI file changed", v1.startswith("9.9.9+") and v1 != v2, f"{v1} {v2}")
    finally:
        p7.terminate()
    c, d = get("/status"); check("47b without TV7_DEV_RELOAD the version is the plain app version", d["version"] == "9.9.9", d["version"])
    # HDMI watcher: no display for a while -> playback stops; display back -> the same channel starts again (hdmi_disconnect=resume)
    p8 = subprocess.Popen([sys.executable, "-I", CONTROL, SOCK, "18775"], env=dict(env, TV7_UI_PORT="0", TV7_HDMI_OFF_S="1", TV7_HDMI_BACK_S="0.5", TV7_HDMI_POLL_S="0.2"))
    time.sleep(1)
    def get8(path):
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:18775{path}", timeout=60); return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)
    try:
        state.update(scenario="ok", cable=True, loads=0, stops=0); hdmi_write("connected")
        get8("/play?channel=SRF%201&source=multicast")
        state["cable"] = False; hdmi_write("disconnected"); time.sleep(2)
        c, d = get8("/status")
        check("49 HDMI disconnected for longer than the limit: playback stops, the status says why", state["stops"] == 1 and state["loaded"] is None
              and d["channel"] is None and d["hdmi_stopped"] == {"channel": "SRF 1", "resume": True}, str((state["stops"], d.get("hdmi_stopped"))))
        loads = state["loads"]; state["cable"] = True; hdmi_write("connected"); time.sleep(3)
        c, d = get8("/status")
        check("49b display back: the same channel starts again", state["loads"] > loads and str(state["loaded"]).startswith("udp://233.50.230.80")
              and d["channel"] == "SRF 1" and d["hdmi_stopped"] is None, str((state["loaded"], d.get("channel"))))
        state["cable"] = False; hdmi_write("disconnected"); time.sleep(0.5); get8("/stop"); time.sleep(2)
        check("49c a manual stop is not resumed", get8("/status")[1]["hdmi_stopped"] is None)
        hdmi_write("connected"); state["cable"] = True
    finally:
        p8.terminate()
    open(f"{tmp}/options-keep.json", "w").write(json.dumps({"hdmi_disconnect": "keep"}))
    time.sleep(0.5)
    p9 = subprocess.Popen([sys.executable, "-I", CONTROL, SOCK, "18775"], env=dict(env, TV7_OPTIONS=f"{tmp}/options-keep.json", TV7_UI_PORT="0", TV7_HDMI_OFF_S="1", TV7_HDMI_POLL_S="0.2"))
    time.sleep(1)
    try:
        state.update(stops=0); get8("/play?channel=SRF%201&source=multicast")
        state["cable"] = False; hdmi_write("disconnected"); time.sleep(2)
        check("49d hdmi_disconnect=keep: playback goes on without a display", state["stops"] == 0 and state["loaded"] is not None, str(state["stops"]))
        state["cable"] = True; hdmi_write("connected")
    finally:
        p9.terminate()
    # HDMI-CEC (option cec): fake cec-ctl with two adapters, only cec1 has a display (physical address); mode file: free | used | ours
    open(f"{tmp}/cec0", "w").close(); open(f"{tmp}/cec1", "w").close()
    open(f"{tmp}/cec-ctl", "w").write(f"""#!/bin/bash
echo "$*" >> {tmp}/cec-calls
mode=$(cat {tmp}/cec-mode)
dev=$2
case "$3" in
  "") phys=3.0.0.0; [ "${{dev##*/}}" = cec0 ] && phys=f.f.f.f
      mask=0x0000; osd=""; [ "$mode" = used ] && mask=0x0010 && osd="CEC Adapter"; [ "$mode" = ours ] && mask=0x0010 && osd=TV7
      printf 'Driver Info:\n\tDriver Name                : vc4_hdmi\n\tPhysical Address           : %s\n\tLogical Address Mask       : %s\n\tOSD Name                   : %s\n' "$phys" "$mask" "'$osd'" ;;
  -S) printf '\tSystem Information for device 0 (TV) from device 4 (Playback Device 1):\n\t\tPhysical Address           : 0.0.0.0\n\t\tVendor ID                  : 0x00e091 (LG)\n\t\tOSD Name                   : %s\n\t\tPower Status               : On\n' "'Beamer'"
      printf '\tSystem Information for device 3 (Tuner 1) from device 4 (Playback Device 1):\n\t\tOSD Name                   : Tx, OK, Rx, Timeout\n'
      printf '\tSystem Information for device 5 (Audio System) from device 4 (Playback Device 1):\n\t\tPhysical Address           : 3.0.0.0\n\t\tOSD Name                   : %s\n\t\tPower Status               : Standby\n' "'AVR-X2200W'"
      printf '\tTopology:\n\n\t0.0.0.0: TV\n\t    3.0.0.0: Audio System\n\t        3.1.0.0: Playback Device 1\n' ;;
  -W) printf 'Received from TV to Playback Device 1 (0 to 4): USER_CONTROL_PRESSED (0x44):\n\tui-cmd: up (0x01)\n'
      printf 'Received from TV to Playback Device 1 (0 to 4): USER_CONTROL_PRESSED (0x44):\n\tui-cmd: select (0x00)\n'
      printf 'Received from TV to Playback Device 2 (0 to 8): GIVE_DEVICE_POWER_STATUS (0x8f)\n\tSequence: 0 Rx Timestamp: x\n'
      printf 'Received from TV to all (0 to 15): SET_STREAM_PATH (0x86):\n\tphys-addr: 3.0.0.0\n'
      for _ in $(seq 1 150); do if [ -e {tmp}/cec-go ]; then cat {tmp}/cec-rx; rm -f {tmp}/cec-go; fi; sleep 0.1; done ;;
esac
""")
    os.chmod(f"{tmp}/cec-ctl", 0o755)
    def cec_run(mode, on, port, core=None, during=None, rx=False):
        """Start control.py with option cec (auto/off) against the fake cec-ctl; core = Home Assistant's /api/config (None: not reachable).
        during(st) is called while the state is "waiting" (Home Assistant still starting). Returns the CEC state, cec-ctl calls, settings item."""
        open(f"{tmp}/cec-mode", "w").write(mode); open(f"{tmp}/cec-calls", "w").close(); sup["core"] = core
        open(f"{tmp}/options-cec.json", "w").write(json.dumps({"cec": "auto" if on else "off"}))
        pc = subprocess.Popen([sys.executable, "-I", CONTROL, SOCK, str(port)], env=dict(env, TV7_OPTIONS=f"{tmp}/options-cec.json", TV7_UI_PORT="0",
                              TV7_CEC_CTL=f"{tmp}/cec-ctl", TV7_CEC_GLOB=f"{tmp}/cec[0-9]", TV7_CEC_CORE_POLL_S="0.2", TV7_CEC_CORE_WAIT_S="1.5",
                              TV7_CEC_AWAY_S="1", TV7_HDMI_POLL_S="0.2"))
        try:
            st, item, seen = {}, {}, set()
            for _ in range(60):
                time.sleep(0.25)
                try:
                    st = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/environment", timeout=10))["cec"]
                except Exception:
                    continue
                seen.add(st["state"])
                if st["state"] == "waiting" and during:
                    during(st); during = None
                if st["state"] not in ("off", "waiting") or not on and "--clear" in open(f"{tmp}/cec-calls").read():
                    break
            item = next(x for x in json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/settings", timeout=10))["items"] if x["key"] == "cec")
            st["seen"] = sorted(seen)
            if st["state"] == "active":                           # the message receiver runs in the background
                time.sleep(0.8)
                st["nerd_log"] = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/nerd", timeout=10))["cec"]["log"]
                st["support"] = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/support", timeout=30))["text"]
                n_as = open(f"{tmp}/cec-calls").read().count("--active-source")
                urllib.request.urlopen(f"http://127.0.0.1:{port}/play?channel=SRF%201", timeout=30).read(); time.sleep(0.5)
                st["active_after_play"] = open(f"{tmp}/cec-calls").read().count("--active-source") - n_as
                if rx:                                            # CEC messages from the TV while a channel plays
                    def send(text, wait):
                        open(f"{tmp}/cec-rx", "w").write(text); open(f"{tmp}/cec-go", "w").close(); time.sleep(wait)
                        return json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=10))
                    st["rx"] = [send("Received from TV to all (0 to 15): STANDBY (0x36)\n", 1.0)]
                    st["rx"].append(send("Received from TV to all (0 to 15): SET_STREAM_PATH (0x86):\n\tphys-addr: 3.0.0.0\n", 2.5))
                    st["rx"].append(send("Received from Playback Device 1 to all (4 to 15): ACTIVE_SOURCE (0x82):\n\tphys-addr: 3.4.0.0\n", 0.4))
                    time.sleep(1.5)
                    st["rx"].append(json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=10)))
            return st, open(f"{tmp}/cec-calls").read(), item
        finally:
            pc.terminate()
    RUNNING = {"state": "RUNNING", "components": ["http", "api", "media_player"]}
    state["osd"] = []
    st, calls, item = cec_run("free", True, 18777, core=RUNNING, rx=True)
    check("56 cec auto, no HDMI-CEC integration, port free: registers as TV7 on the adapter with a display (cec1) and lists the devices",
          st["state"] == "active" and st["device"].endswith("cec1") and "cec1 --playback --osd-name=TV7" in calls and "cec1 -S" in calls
          and [d["name"] for d in st["devices"]] == ["Beamer", None, "AVR-X2200W"] and st["devices"][0]["vendor"] == "0x00e091 (LG)"
          and st["topology"][-1].strip() == "3.1.0.0: Playback Device 1", str(st) + calls)
    check("56a the option is not greyed out when the app uses CEC", "locked" not in item, str(item))
    cl = "\n".join(st.get("nerd_log", []))
    check("56k CEC messages in nerd mode: received through cec-ctl -W, key press logged",
          "-W -w ---" in cl and " -m " not in cl and "USER_CONTROL_PRESSED" in cl and "ui-cmd: up (0x01)" in cl, cl)
    check("56m CEC: power status answered to the asking TV, active source confirmed when the TV switches to the app's address",
          "cec1 --to=0 --report-power-status=pwr-state=on" in calls and "cec1 --active-source=phys-addr=3.0.0.0" in calls, calls)
    check("56o a channel start announces the app as the active source (keys of the TV remote come to the app)", st.get("active_after_play", 0) >= 1, str(st.get("active_after_play")))
    rxs = st.get("rx") or [{}] * 4
    check("56p CEC: the TV switches to standby -> playback stops (reason cec)", not rxs[0].get("playing") and (rxs[0].get("autostopped") or {}).get("reason") == "cec", str(rxs[0].get("autostopped")))
    check("56q CEC: the TV shows TV7 again -> the channel resumes", rxs[1].get("playing") is True and rxs[1].get("channel") == "SRF 1", str(rxs[1].get("channel")))
    check("56r CEC: another source -> still playing during the grace time, then stopped", rxs[2].get("playing") is True and not rxs[3].get("playing")
          and (rxs[3].get("autostopped") or {}).get("reason") == "cec", str([rxs[2].get("playing"), rxs[3].get("playing")]))
    check("56n support info keeps CEC physical addresses (not masked like IP addresses)", "3.0.0.0: Audio System" in st.get("support", "")
          and "| 3.0.0.0 |" in st.get("support", ""), st.get("support", "")[-800:])
    check("56l a CEC remote key reaches the TV menu (select opens it)", any(o.get("id") == 8 and o.get("format") == "ass-events" for o in state["osd"]), str(len(state["osd"])))
    st, calls, item = cec_run("used", True, 18778, core=RUNNING)
    check("56b cec auto, port used by another program: the app stays out, option greyed out", st["state"] == "in_use" and "--playback" not in calls
          and "CEC Adapter" in st["detail"] and item.get("locked") == "in_use", str(st) + calls + str(item))
    st, calls, item = cec_run("ours", True, 18778, core=RUNNING)
    check("56c cec auto, the app's own registration of an earlier start: not 'in use'", st["state"] == "active", str(st))
    st, calls, item = cec_run("ours", False, 18779)
    check("56d cec off: the app's own registration is removed, nothing else", "cec1 --clear" in calls and "--playback" not in calls and st.get("state") == "off", str(st) + calls)
    st, calls, item = cec_run("used", False, 18779)
    check("56e cec off, another program's registration: untouched", "--clear" not in calls and "--playback" not in calls, calls)
    st, calls, item = cec_run("free", True, 18780, core={"state": "RUNNING", "components": ["http", "hdmi_cec"]})
    check("56h Home Assistant's HDMI-CEC integration active: the app stays out, option greyed out", st["state"] == "ha_integration"
          and "--playback" not in calls and item.get("locked") == "ha_integration", str(st) + calls + str(item))
    st, calls, item = cec_run("free", True, 18781, core={"state": "STARTING", "components": ["http"]},
                              during=lambda _: sup.update(core={"state": "RUNNING", "components": ["http", "hdmi_cec"]}))
    check("56i Home Assistant still starting: the app waits, then sees the integration loaded meanwhile", "waiting" in st["seen"]
          and st["state"] == "ha_integration" and "--playback" not in calls, str(st) + calls)
    st, calls, item = cec_run("free", True, 18782, core=None)
    check("56j Home Assistant not reachable: after the wait only the port decides", st["state"] == "active" and "cec1 --playback" in calls, str(st) + calls)
    c, d = get("/environment"); check("56f cec auto (default) without a CEC device: no_device, nothing else", d["cec"]["state"] == "no_device", str(d.get("cec")))
    c, d = get("/support"); check("56g support info has the CEC state", "## HDMI-CEC" in d["text"] and "State: no_device" in d["text"], "")

    # idle_stop: stop after that many hours without operation (TV7_MINUTE_S shortens a minute to 40 ms: 60 min = 2.4 s)
    open(f"{tmp}/options-idle.json", "w").write(json.dumps({"idle_stop": "60"}))
    p10 = subprocess.Popen([sys.executable, "-I", CONTROL, SOCK, "18776"], env=dict(env, TV7_OPTIONS=f"{tmp}/options-idle.json", TV7_UI_PORT="0",
                           TV7_MINUTE_S="0.04", TV7_HDMI_POLL_S="0.1"))
    time.sleep(1)
    def get10(path):
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:18776{path}", timeout=60); return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)
    try:
        state.update(scenario="ok", cable=True, stops=0); hdmi_write("connected")
        get10("/play?channel=SRF%201&source=multicast")
        for _ in range(15):
            get10("/volume?d=0"); time.sleep(0.2)
        check("52 operating the player (volume) keeps idle_stop from stopping it", state["stops"] == 0, str(state["stops"]))
        time.sleep(3); c, d = get10("/status")
        check("52b idle_stop=60: no operation for 60 min (shortened) stops playback, the status says why", state["stops"] == 1 and d["autostopped"] == {**d["autostopped"], "reason": "idle", "minutes": 60}, str(d.get("autostopped")))
        get10("/play?channel=SRF%201&source=multicast")
        check("52c a new start clears the stop note", get10("/status")[1]["autostopped"] is None)
        get10("/stop")
    finally:
        p10.terminate()
finally:
    p.terminate()
r = subprocess.run([sys.executable, os.path.join(HERE, "test_player.py")], capture_output=True, text=True, timeout=120)
print(r.stdout.strip())
check("45 starting and supervising mpv: decoder per device, audio device, restarts (tests/test_player.py)", r.returncode == 0, r.stderr[-500:])
print("FAILURES:", fails)
sys.exit(1 if fails else 0)

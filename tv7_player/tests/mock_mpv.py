#!/usr/bin/env python3
"""A fake mpv for the tests and for developing the web UI without a display, sound card or TV7 network (dev/run-web.sh).

It answers mpv's JSON IPC like mpv does: a connection stays open for any number of commands, request ids are echoed, log
messages are pushed to a client that asks for them, and "quit" ends the client's connection (as when mpv restarts, with
a new pid). It "plays" whatever it is told to load. Everything it is told is recorded in `state` for the tests.

Module:     MockMpv(socket_path, state, can_start=lambda url: True, log_lines=[...]).serve()
Standalone: python3 mock_mpv.py <socket path>       (sends a log line every few seconds)
"""

import json
import os
import socket
import sys
import threading
import time


class MockMpv:
    def __init__(self, sock, state=None, can_start=None, log_lines=None, log_every=None):
        self.sock = sock
        self.state = state if state is not None else {}
        for k, v in (("loaded", None), ("t0", 0.0), ("loads", 0), ("pid", 4242), ("volume", 100), ("mute", False)):
            self.state.setdefault(k, v)
        self.can_start = can_start or (lambda url: True)
        self.log_lines = log_lines if log_lines is not None else []  # (prefix, text) sent once to a log client
        self.log_every = log_every  # seconds between further log lines (dev)

    def prop(self, name):
        st = self.state
        run = bool(st["loaded"]) and self.can_start(st["loaded"]) and time.time() - st["t0"] > 0.3
        fps = st.get("fps", 50.0)
        return {
            "idle-active": not run,
            "video-codec": "h264" if run and not st.get("novideo") else None,
            "time-pos": time.time() - st["t0"] if run else None,
            "media-title": st["loaded"],
            "path": st["loaded"],
            "file-format": "mpegts" if run else None,
            "pid": st["pid"],
            "mpv-version": "mpv 0.40.0 (mock)",
            "ffmpeg-version": "7.1",
            "volume": st["volume"],
            "mute": st["mute"],
            "audio-codec-name": "ac3" if run else None,
            "audio-codec": "ATSC A/52A (AC-3)" if run else None,
            "audio-device": "pulse/alsa_output.platform-107c701400.hdmi.hdmi-stereo",
            "current-ao": "alsa" if run else None,
            "audio-params": {"format": "floatp", "samplerate": 48000, "hr-channels": "stereo"} if run else None,
            "audio-out-params": {"format": "float", "samplerate": 48000, "hr-channels": "stereo"} if run else None,
            "audio-bitrate": 384000 if run else None,
            "audio-device-list": [
                {"name": "auto"},
                {"name": "pulse/alsa_output.platform-107c701400.hdmi.hdmi-stereo"},
                {"name": "alsa/hdmi:CARD=vc4hdmi0,DEV=0"},
            ],
            "track-list": (
                [
                    {"type": "video", "id": 1},
                    {
                        "type": "audio",
                        "id": 1,
                        "lang": "deu",
                        "codec": "ac3",
                        "demux-channel-count": 2,
                        "selected": True,
                    },
                    {
                        "type": "audio",
                        "id": 2,
                        "lang": "eng",
                        "codec": "ac3",
                        "demux-channel-count": 2,
                        "selected": False,
                    },
                    {
                        "type": "sub",
                        "id": 1,
                        "lang": "deu",
                        "title": "Teletext",
                        "codec": "dvb_teletext",
                        "selected": False,
                    },
                ]
                if run
                else []
            ),
            "video-format": "h264" if run else None,
            "video-bitrate": 6400000 if run else None,
            "video-params": {
                "pixelformat": "yuv420p",
                "w": 1280,
                "h": 720,
                "colormatrix": "bt.709",
                "primaries": "bt.709",
                "gamma": "bt.1886",
            }
            if run
            else None,
            "video-params/w": 1280,
            "video-params/h": 720,
            "container-fps": fps,
            "estimated-vf-fps": fps if run else None,
            "hwdec": "auto-safe",
            "hwdec-current": "drm" if st.get("hw") else "no",
            "deinterlace": st.get("deint"),
            "vf": [],
            "frame-drop-count": 3,
            "decoder-frame-drop-count": 1,
            "vo-delayed-frame-count": 0,
            "mistimed-frame-count": 0,
            "avsync": 0.004 if run else None,
            "total-avsync-change": 0.0,
            "osd-width": 1920,
            "osd-height": 1080,
            "display-fps": 50.0,
            "current-vo": "drm",
            "options/drm-device": "/dev/dri/card1",
            "options/drm-connector": "",
            "options/drm-mode": "preferred",
            "options/drm-draw-plane": "overlay",
            "options/drm-drmprime-video-plane": "primary",
            "options/gpu-hwdec-interop": "",
            "options/hwdec-codecs": "hevc",
        }.get(name)

    def handle(self, conn):
        buf = b""
        try:
            while True:
                while b"\n" not in buf:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    buf += chunk
                line, buf = buf.split(b"\n", 1)
                if line.strip() and not self.command(conn, json.loads(line)):
                    return
        except OSError:
            pass
        finally:
            conn.close()

    def command(self, conn, req):
        """One command; returns False when the connection ends (quit, end of a log stream)."""
        st, cmd = self.state, req["command"]
        out = {"error": "success", "data": None}
        if "request_id" in req:
            out["request_id"] = req["request_id"]

        def send(obj):
            conn.sendall((json.dumps(obj) + "\n").encode())

        if isinstance(cmd, dict):  # named arguments (osd-overlay)
            st.setdefault("osd", []).append(cmd)
            send(out)
            return True
        name = cmd[0]
        if name == "loadfile":
            st.update(loaded=cmd[1], t0=time.time(), loads=st["loads"] + 1)
        elif name == "get_property":
            out["data"] = self.prop(cmd[1])
        elif name == "request_log_messages":
            send(out)
            st["log_requests"] = st.get("log_requests", 0) + 1
            for prefix, text in self.log_lines:
                send({"event": "log-message", "prefix": prefix, "level": "info", "text": text + "\n"})
            if not self.log_every:
                time.sleep(30)
                return False
            n = 0
            while True:
                n += 1
                time.sleep(self.log_every)
                send(
                    {
                        "event": "log-message",
                        "prefix": "cplayer",
                        "level": "info",
                        "text": f"mock log line {n} (playing {st['loaded']})\n",
                    }
                )
        elif name == "quit":
            st["quit"] = st.get("quit", 0) + 1
            st["pid"] += 1  # the supervision (tv7/mpvhost.py) starts mpv again: a new process
        elif name == "stop":
            st.update(loaded=None, stops=st.get("stops", 0) + 1)
        elif name == "set_property" and cmd[1] in ("volume", "mute"):
            st[cmd[1]] = cmd[2]
        elif name == "set_property" and cmd[1] in ("deinterlace", "sid", "aid"):
            st[{"deinterlace": "deint"}.get(cmd[1], cmd[1])] = cmd[2]
        elif name in ("overlay-add", "overlay-remove"):
            st.setdefault("ovl", []).append(cmd)
        send(out)
        return name != "quit"

    def serve(self):
        if os.path.exists(self.sock):
            os.remove(self.sock)
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(self.sock)
        srv.listen(5)

        def loop():
            while True:
                c, _ = srv.accept()
                threading.Thread(target=self.handle, args=(c,), daemon=True).start()

        threading.Thread(target=loop, daemon=True).start()
        return self


if __name__ == "__main__":
    MockMpv(sys.argv[1], log_every=3).serve()
    while True:
        time.sleep(3600)

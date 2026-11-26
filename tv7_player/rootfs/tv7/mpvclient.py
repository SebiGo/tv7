"""Talking to mpv over its IPC socket: commands and properties (one connection that stays open), the log and change
notifications (a second connection), the tracks of the running stream."""

import json
import socket
import threading
import time

from tv7 import config

SOCK = ""
_ovl_conn = {"sock": None, "buf": b"", "id": 0}
_ovl_conn_lock = threading.Lock()


def mpv_keep(cmd):
    """An mpv command over the one connection that stays open (mpv starts a thread per connection, and it removes the
    OSD overlays of a client when its connection closes). Reconnects after an mpv restart. The log reader has its own
    connection."""
    with _ovl_conn_lock:
        for attempt in (1, 2):
            c = _ovl_conn
            try:
                if c["sock"] is None:
                    s = socket.socket(socket.AF_UNIX)
                    s.settimeout(3)
                    s.connect(SOCK)
                    # events would only pile up unread
                    s.sendall(b'{"command": ["disable_event", "all"], "request_id": 0}\n')
                    c.update(sock=s, buf=b"")
                c["id"] += 1
                rid = c["id"]
                c["sock"].sendall((json.dumps({"command": cmd, "request_id": rid}) + "\n").encode())
                while True:  # skip events and answers to other requests
                    while b"\n" not in c["buf"]:
                        chunk = c["sock"].recv(65536)
                        if not chunk:
                            raise ConnectionError("mpv closed the connection")
                        c["buf"] += chunk
                    line, c["buf"] = c["buf"].split(b"\n", 1)
                    msg = json.loads(line or b"{}")
                    if msg.get("request_id") == rid and "error" in msg:
                        return msg
            except (OSError, ValueError):
                try:
                    if c["sock"]:
                        c["sock"].close()
                except OSError:
                    pass  # the socket is gone already
                c.update(sock=None, buf=b"")
                if attempt == 2:
                    raise


def mpv_named(**cmd):
    """An mpv command with named arguments (osd-overlay), over the connection that keeps the overlays alive."""
    return mpv_keep(cmd)


def mpv(*cmd):
    """An mpv command (positional arguments)."""
    return mpv_keep(list(cmd))


def prop(name):
    try:
        return mpv("get_property", name).get("data")
    except Exception:
        return None


def playing():
    """Is a video playing? (not idle, video codec known, time advancing)"""
    return prop("idle-active") is False and bool(prop("video-codec")) and (prop("time-pos") or 0) > 0


LOG_LINES = 150
_mpv_log = []  # last mpv log messages (ring buffer)
_log_lock = threading.Lock()
_log_thread = {"started": False}
# What the web UI shows changed: mpv reported a change, or the app started/stopped something. /events waits for this.
_changed = threading.Condition()
_version = {"n": 0}
# Called (in a thread of its own) when playback ends (mpv goes idle); control.py adds the TV overlay's update.
on_idle = []
OBSERVED = (
    "idle-active",
    "media-title",
    "volume",
    "mute",
    "track-list",
    "current-ao",
    "hwdec-current",
    "video-params",
    "display-fps",
)


def changed():
    with _changed:
        _version["n"] += 1
        _changed.notify_all()


def wait_change(seen, timeout):
    """Wait until something changed after version seen (or timeout); returns the current version."""
    with _changed:
        _changed.wait_for(lambda: _version["n"] != seen, timeout=timeout)
        return _version["n"]


def _log_reader():
    """Keep an IPC connection to mpv open: it collects mpv's log messages (request_log_messages) and is told about
    changes of the properties the web UI shows (observe_property), which wake up /events. Reconnects when mpv
    restarts."""
    while True:
        try:
            s = socket.socket(socket.AF_UNIX)
            s.settimeout(None)
            s.connect(SOCK)
            for i, name in enumerate(OBSERVED, 1):
                s.sendall((json.dumps({"command": ["observe_property", i, name]}) + "\n").encode())
            s.sendall((json.dumps({"command": ["request_log_messages", "info"]}) + "\n").encode())
            changed()
            buf = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("event") == "property-change":
                        changed()
                        if ev.get("name") == "idle-active" and ev.get("data") is True:
                            for fn in on_idle:
                                threading.Thread(target=fn, daemon=True).start()
                    elif ev.get("event") == "log-message":
                        text = f"[{ev.get('prefix', '')}] {ev.get('level', '')}: {str(ev.get('text', '')).rstrip()}"
                        with _log_lock:
                            _mpv_log.append(time.strftime("%H:%M:%S ") + text)
                            del _mpv_log[:-LOG_LINES]
            s.close()
        except (ConnectionError, FileNotFoundError):
            pass  # mpv is (re)starting: connect again
        except Exception as e:
            config.log_once("mpv log reader", e)
        time.sleep(2)


def mpv_log():
    """The reader is started at program start (main) and, as a fallback, on first use."""
    if not _log_thread["started"] and SOCK:
        _log_thread["started"] = True
        threading.Thread(target=_log_reader, daemon=True).start()
    with _log_lock:
        return list(_mpv_log)


def tracks():
    out = {"audio": [], "sub": []}
    for t in prop("track-list") or []:
        kind = {"audio": "audio", "sub": "sub"}.get(t.get("type"))
        if kind:
            out[kind].append(
                {
                    "id": t.get("id"),
                    "lang": t.get("lang"),
                    "title": t.get("title"),
                    "codec": t.get("codec"),
                    "channels": t.get("demux-channel-count"),
                    "selected": bool(t.get("selected")),
                    "external": bool(t.get("external")),
                }
            )
    return out

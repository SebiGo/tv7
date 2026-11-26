"""Channel list, channel start (multicast, HLS, retries, no display), source choice, volume, tracks, /status and
/events."""

import threading
import time


def test_health_and_no_token(app):
    assert app.get("/health")[0] == 200
    assert app.get("/channels")[0] == 200, "the API needs no token (it is only reachable on this device)"


def test_api_listens_on_localhost_only(app):
    with open("/proc/net/tcp") as f:
        rows = [line.split() for line in f.read().splitlines()[1:]]
    listening = [r[1] for r in rows if r[3] == "0A" and r[1].endswith(f":{app.port:04X}")]
    assert listening == [f"0100007F:{app.port:04X}"]


def test_channel_list(app, world):
    c, d = app.get("/channels")
    assert c == 200 and any(x["name"] == "SRF 1" for x in d)
    assert world.live or len(d) == 4, f"{len(d)} channels"
    assert all(x["name"] != "Hidden" for x in d), "hidden channels are missing"


def test_start_multicast(app, world):
    world.ready()
    c, d = app.get("/play?channel=SRF%201")
    assert c == 200 and d["source"] == "multicast" and not any("HDMI" in x for x in d["log"]), d["log"]
    assert world.state["loaded"].startswith("udp://233.") and "@" not in world.state["loaded"], (
        "multicast address without '@'"
    )


def test_start_without_display_only_reads_sysfs(app, world):
    """HDMI disconnected: the channel starts anyway with a note; sysfs is only read (no 'detect' written)."""
    world.ready()
    world.hdmi("disconnected")
    c, d = app.get("/play?channel=SRF%20zwei")
    time.sleep(0.2)
    assert c == 200 and any("no display connected" in x for x in d["log"]), d["log"]
    assert world.hdmi_read() == "disconnected"


def test_stream_without_picture_output_stops_at_once(app, world):
    """The stream is received but mpv has no picture output: a clear reason, no retries."""
    world.ready(novideo=True)
    world.hdmi("disconnected")
    t = time.time()
    try:
        c, d = app.get("/play?channel=SRF%20zwei")
        loads = world.state["loads"]
    finally:
        world.ready()
    assert c == 502 and d.get("reason") == "no_display" and loads == 1, d["log"]
    assert time.time() - t < 5 and any("no display is connected" in x for x in d["log"]), d["log"]


def test_multicast_fails_then_hls(app, world):
    world.ready(scenario="multicast_fails")
    c, d = app.get("/play?channel=pk-srf1")
    assert c == 200 and d["source"] == "hls" and world.state["loads"] == 3, d["log"]
    assert not any("reset" in x.lower() for x in d["log"]), d["log"]
    assert world.state["loaded"].startswith("https://api.tv.init7.net/api/live/"), "HLS URL from Init7"


def test_nothing_starts(app, world):
    world.ready(scenario="never")
    c, d = app.get("/play?channel=SRF%201")
    world.ready()
    assert c == 502 and not d["ok"] and len(d["log"]) >= 4, d["log"]


def test_channel_selection_is_validated(app, world):
    assert app.get("/play?channel=does-not-exist-xyz")[0] == 404
    assert app.get("/play?channel=http://evil.example/x.m3u8")[0] == 404, "free-form URL"
    assert app.get("/play?channel=SRF%201&source=rtsp")[0] == 400, "invalid source"
    if world.live:
        return
    c, d = app.get("/play?channel=Evil&source=multicast")
    assert c in (404, 502) and "http://evil" not in str(world.state["loaded"]), "tampered sources are rejected"
    assert app.get("/play?channel=Hidden")[0] == 404
    assert app.get("/play?channel=SRF")[0] == 404, "ambiguous partial match"
    c, d = app.get("/play?channel=info")
    assert c in (200, 502) and d.get("channel") == "SRF info", "unique partial match"


def test_explicit_sources(app, world):
    world.ready(scenario="multicast_fails")
    c, d = app.get("/play?channel=SRF%201&source=multicast")
    assert c == 502 and not any(x.startswith("hls") for x in d["log"]), "source=multicast: a multicast failure is final"
    world.ready(scenario="multicast_fails")
    c, d = app.get("/play?channel=SRF%201&source=hls")
    assert c == 200 and d["source"] == "hls" and world.state["loaded"].startswith("https://api.tv.init7.net/"), d
    c, d = app.get("/play?channel=SRF%201&source=auto")
    assert c == 200 and d["source"] == "hls" and any(x.startswith("multicast") for x in d["log"]), d["log"]
    world.ready()


def test_no_hdmi_reset_and_status(app):
    assert app.get("/hdmi/reset")[0] == 404, "no HDMI reset (protection mode on, /sys is read-only)"
    c, d = app.get("/status")
    assert c == 200 and "hdmi" in d
    assert "channel" in d and "mute" in d and "pk" in d


def test_volume_and_mute(app):
    assert app.get("/volume?v=abc")[0] == 400
    assert app.get("/volume?d=-5", ui=True)[0] == 200
    assert app.get("/mute", ui=True)[0] == 200


def test_events_on_change(app, world):
    """/events sends the status at once, then right after a change (not only every TV7_EVENTS_S, here 30 s)."""
    world.ready()
    app.get("/play?channel=SRF%201")
    ev, ctype = app.events(2, lambda: threading.Thread(target=app.get, args=("/stop",)).start())
    assert ctype == "text/event-stream" and len(ev) == 2, ev
    assert ev[0][0]["playing"] is True and ev[1][0]["playing"] is False and ev[1][1] - ev[0][1] < 3


def test_events_through_web_ui(app):
    ev, ctype = app.events(1, ui=True)
    assert ctype == "text/event-stream" and len(ev) == 1 and "playing" in ev[0][0]


def test_deinterlace_only_for_software_decoding(app, world):
    world.ready(hw=False, deint=None)
    app.get("/play?channel=SRF%201")
    assert world.state["deint"] == "auto", "software decoding: deinterlace auto (only interlaced frames)"
    world.ready(hw=True, deint=None)
    app.get("/play?channel=SRF%201")
    world.ready(hw=False)
    assert world.state["deint"] is False, "hardware decoding: deinterlace off"


def test_tracks(app, world):
    world.ready()
    app.get("/play?channel=SRF%201")
    assert app.get("/track?type=audio&id=2")[0] == 200
    assert app.get("/track?type=sub&id=off")[0] == 200
    assert app.get("/track?type=video&id=1")[0] == 400
    assert app.get("/track?type=audio&id=abc")[0] == 400
    app.get("/track?type=sub&id=1")
    c, _ = app.get("/play?channel=SRF%201")
    assert c == 200 and world.state.get("sid") == "no", "every channel starts without subtitles"


def test_status_while_playing(app, world):
    world.ready(fps=50.0)
    app.get("/play?channel=SRF%201")
    d = app.get("/status")[1]
    assert d["vo"] == "drm" and d["hwdec"] in ("no", "drm"), "render path and hardware decoding"
    assert d.get("version") == "9.9.9", "app version (the page reloads itself after an update)"
    assert "cores" in d["system"] and len(d["audio_tracks"]) == 2 and d["sub_tracks"][0]["lang"] == "deu", d
    assert d["pending_restart"] == []
    assert d["stream"] == {"w": 1280, "h": 720, "fps": 50.0} and d["output"] == {"w": 1920, "h": 1080, "hz": 50.0}


def test_missing_parameters_and_unknown_endpoints(app):
    for path in ("/play", "/key", "/track?type=audio", "/icon", "/volume"):
        c, d = app.get(path)
        assert c == 400 and "missing" in d["error"], (path, d)
    assert app.get("/nothing")[0] == 404
    assert app.get("/track?type=video&id=1")[1]["error"] == "type: audio or sub"


def _in_background(fn, *args):
    out = {}
    t = threading.Thread(target=lambda: out.update(res=fn(*args), t=time.time()), daemon=True)
    t.start()
    return t, out


def test_stop_cancels_a_hanging_start(app, world):
    """A stop does not wait until a start that gets nowhere has tried every source (here 4 x 2 s)."""
    world.ready(scenario="never")
    try:
        t, started = _in_background(app.get, "/play?channel=SRF%201")
        time.sleep(0.6)
        t0 = time.time()
        assert app.get("/stop")[0] == 200
        stopped = time.time()
        t.join(5)
    finally:
        world.ready()
    assert stopped - t0 < 2, f"the stop waited {stopped - t0:.1f} s"
    c, d = started["res"]
    assert c == 409 and d.get("reason") == "cancelled" and any("cancelled" in x for x in d["log"]), d


def test_new_start_replaces_a_hanging_start(app, world):
    world.ready(scenario="multicast_fails")
    try:
        t, first = _in_background(app.get, "/play?channel=SRF%201&source=multicast")
        time.sleep(0.6)
        t0 = time.time()
        c, d = app.get("/play?channel=SRF%20zwei&source=hls")
        took = time.time() - t0
        t.join(5)
    finally:
        world.ready()
    assert c == 200 and d["channel"] == "SRF zwei" and took < 3, (c, d, took)
    assert first["res"][0] == 409, first["res"]
    assert app.get("/status")[1]["channel"] == "SRF zwei"

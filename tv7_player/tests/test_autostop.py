"""Automatic stops: no HDMI display (hdmi_disconnect) and no operation (idle_stop)."""

import time


def test_hdmi_gone_stops_and_resumes(world, start_app):
    """No display for a while: playback stops; display back: the same channel starts again (hdmi_disconnect=resume)."""
    a = start_app(TV7_HDMI_OFF_S="1", TV7_HDMI_BACK_S="0.5", TV7_HDMI_POLL_S="0.2")
    world.ready(stops=0)
    try:
        a.get("/play?channel=SRF%201&source=multicast")
        world.state["cable"] = False
        world.hdmi("disconnected")
        time.sleep(2)
        d = a.get("/status")[1]
        assert world.state["stops"] == 1 and world.state["loaded"] is None and d["channel"] is None, d
        assert d["hdmi_stopped"] == {"channel": "SRF 1", "resume": True}, "the status says why"
        loads = world.state["loads"]
        world.state["cable"] = True
        world.hdmi("connected")
        time.sleep(3)
        d = a.get("/status")[1]
        assert world.state["loads"] > loads and str(world.state["loaded"]).startswith("udp://233.50.230.80"), "resumed"
        assert d["channel"] == "SRF 1" and d["hdmi_stopped"] is None
        world.state["cable"] = False
        world.hdmi("disconnected")
        time.sleep(0.5)
        a.get("/stop")
        time.sleep(2)
        assert a.get("/status")[1]["hdmi_stopped"] is None, "a manual stop is not resumed"
    finally:
        world.ready()


def test_hdmi_gone_keep(world, start_app):
    opts = world.options_file("options-keep.json", {"hdmi_disconnect": "keep"})
    a = start_app(TV7_OPTIONS=opts, TV7_HDMI_OFF_S="1", TV7_HDMI_POLL_S="0.2")
    world.ready(stops=0)
    try:
        a.get("/play?channel=SRF%201&source=multicast")
        world.state["cable"] = False
        world.hdmi("disconnected")
        time.sleep(2)
        assert world.state["stops"] == 0 and world.state["loaded"] is not None, "playback goes on without a display"
    finally:
        world.ready()


def test_idle_stop(world, start_app):
    """idle_stop=60 with TV7_MINUTE_S shortening a minute to 40 ms (60 min = 2.4 s)."""
    opts = world.options_file("options-idle.json", {"idle_stop": "60"})
    a = start_app(TV7_OPTIONS=opts, TV7_MINUTE_S="0.04", TV7_HDMI_POLL_S="0.1")
    world.ready(stops=0)
    a.get("/play?channel=SRF%201&source=multicast")
    for _ in range(15):
        a.get("/volume?d=0")
        time.sleep(0.2)
    assert world.state["stops"] == 0, "operating the player (volume) keeps idle_stop from stopping it"
    time.sleep(3)
    d = a.get("/status")[1]
    assert world.state["stops"] == 1 and d["autostopped"] == {**d["autostopped"], "reason": "idle", "minutes": 60}, d
    a.get("/play?channel=SRF%201&source=multicast")
    assert a.get("/status")[1]["autostopped"] is None, "a new start clears the stop note"
    a.get("/stop")

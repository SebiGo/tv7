"""The output mode follows the stream's frame rate, and a video output chosen without a display is chosen again."""

import json
import urllib.request


def override(a):
    return json.load(urllib.request.urlopen(a.url("/nerd"), timeout=30))["output"]["drm_mode_override"]


def test_refresh_follows_the_stream(world, start_app):
    """Stream 50 fps, display preferred 3840x2160@60; 1080p50 is index 3, 1080p59.94 index 4."""
    opts = world.options_file("options-auto.json", {"video_mode": "auto"})
    a = start_app(TV7_OPTIONS=opts)
    world.ready(quit=0, hw=False, fps=50.0)
    c, d = a.get("/play?channel=SRF%201")
    assert c == 200 and world.state["quit"] == 0 and override(a) is None, "starts at 1080p50: no switch for 50 fps"
    world.state.update(fps=59.94, loads=0)
    c, d = a.get("/play?channel=SRF%201")
    assert c == 200 and override(a) == "4" and world.state["quit"] == 1 and world.state["loads"] == 2, d["log"]
    assert any("follows the stream" in x for x in d["log"]), d["log"]
    c, d = a.get("/play?channel=SRF%201")
    assert c == 200 and world.state["quit"] == 1, "the same frame rate again: no further restart"
    world.state.update(fps=50.0)
    c, d = a.get("/play?channel=SRF%201")
    assert c == 200 and override(a) == "3" and world.state["quit"] == 2, "back to 50 fps: 1080p50 again"


def test_started_with_preferred_mode_switches_to_50(world, start_app):
    """mpv was started without a display ("preferred" = 4K60 here); that start mode is known, so a 50 fps stream
    switches."""
    opts = world.options_file("options-auto.json", {"video_mode": "auto"})
    a = start_app(TV7_OPTIONS=opts, TV7_VIDEO="vo=gpu pending=no hw=no mode=preferred")
    world.ready(quit=0, fps=50.0)
    c, d = a.get("/play?channel=SRF%201")
    assert override(a) == "3" and world.state["quit"] == 1, d["log"]


def test_pending_video_output(world, start_app):
    """Video output chosen without a display (TV off when the app started): chosen again once a display is connected."""
    a = start_app(TV7_VIDEO="vo=drm pending=yes hw=no")
    world.ready(quit=0, cable=False)
    world.hdmi("disconnected")
    c, d = a.get("/play?channel=SRF%201")
    assert world.state["quit"] == 0, "still no display: no restart"
    world.ready()
    c, d = a.get("/play?channel=SRF%201")
    assert world.state["quit"] == 1 and any("choosing the video output again" in x for x in d["log"]), d["log"]

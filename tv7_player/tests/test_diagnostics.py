"""Nerd mode (/nerd) and the support text (/support): technical details, mpv log, masking of secrets."""

import json

from fakes import wait_for


def test_nerd(app, world):
    world.ready()
    app.get("/play?channel=SRF%201")
    c, d = app.get("/nerd")
    assert c == 200 and d["video"]["codec"] == "h264" and d["video"]["bitrate"] == 6400000, d["video"]
    assert d["frames"]["dropped_vo"] == 3 and d["frames"]["dropped_decoder"] == 1
    out = d["output"]
    assert out["drm_device"] == "/dev/dri/card1" and out["draw_plane"] == "overlay" and out["video_plane"] == "primary"
    assert d["audio"]["samplerate"] == 48000 and "clock" in d["system"] and "memory" in d["system"]
    assert isinstance(d["log"], list)
    c, body = app.page("/nerd")
    assert c == 200 and "log" in json.loads(body), "/nerd on the web UI port"


def test_nerd_collects_the_mpv_log(app, world):
    """mpv's log comes through request_log_messages."""
    log = wait_for(lambda: [x for x in app.get("/nerd")[1]["log"] if "[vo/drm] info: mock line 2" in x])
    assert log and world.state.get("log_requests", 0) >= 1


def support(app, world):
    world.ready()
    app.get("/play?channel=SRF%201&source=multicast")
    c, d = app.get("/support")
    assert c == 200
    return d.get("text", "")


def test_support_layout(app, world):
    t = support(app, world)
    for h in ("## Problem/Motivation", "## Steps to reproduce", "## System", "## Playback", "## Display output",
              "## Environment", "## Options", "<details>"):  # fmt: skip
        assert h in t, h
    assert "| TV7 Player | 9.9.9 |" in t and "HDMI-A-1" in t and "/dev/dri/card1" in t and "mock line 2" in t


def test_support_masks_secrets(app, world):
    """Bearer tokens, URL parameters, unicast IPs and options of older versions are masked; multicast addresses stay."""
    t = support(app, world)
    for secret in ("secret-should-not-show", "api_token", "eyJ.secret", "sig=abc", "192.168.1.20"):
        assert secret not in t, secret
    assert "udp://233.50.230.80:5000" in t


def test_support_last_start_and_sync(app, world):
    t = support(app, world)
    assert "## Last channel start" in t and "multicast: started" in t, t[t.find("## Last channel start") :][:600]
    assert "| TV7 channels | 4 |" in t or world.live
    assert "Last successful sync" in t and "waiting for a restart: none" in t and "Report created" in t


def test_support_versions_and_app_log(app, world):
    """HAOS/Core versions and machine from the Supervisor, its app log without colour codes and masked."""
    t = support(app, world)
    assert "| Home Assistant OS | 16.3 |" in t and "| Home Assistant Core | 2026.11.2 |" in t
    assert "raspberrypi5-64 / aarch64" in t and ">>> Video output (auto): gpu" in t
    assert "\x1b" not in t and "10.1.2.3" not in t and "token=abc" not in t
    assert world.sup.get("range", "").startswith("entries=")


def test_support_without_cec_device(app):
    c, d = app.get("/environment")
    assert d["cec"]["state"] == "no_device", "cec auto (default) without a CEC device"
    t = app.get("/support")[1]["text"]
    assert "## HDMI-CEC" in t and "State: no_device" in t

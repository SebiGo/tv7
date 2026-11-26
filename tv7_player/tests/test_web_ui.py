"""The Ingress web UI: page, logo, access, settings (choices, validation, saving), favorites, live reload."""

import json
import os
import time
import urllib.request


def test_page_and_logo(app):
    c, body = app.page("/")
    assert c == 200 and "<title>TV7 Player</title>" in body
    assert 'id="nerd-toggle" aria-pressed="false"' in body and 'id="nerd-card" hidden' in body, (
        "nerd mode off by default"
    )
    assert 'id="remote"' not in body and 'data-k="ok"' not in body, "no remote pad (the TV menu uses the TV remote)"
    assert "osd-field" not in body and 'id="osd-on"' not in body, "no TV info switch (TV menu or /osd)"
    status, data = app.get("/status", ui=True)
    assert status == 200 and "hdmi" in data, "the UI port serves the API without token"
    r = urllib.request.urlopen(app.url("/logo.png", ui=True), timeout=30)
    assert r.status == 200 and r.read(4) == b"\x89PNG"


def test_texts_of_all_languages(app):
    c, body = app.page("/")
    assert c == 200 and "/*I18N*/" not in body
    for fav in ('"favTitle": "Favoriten"', '"favTitle": "Favoris"', '"favTitle": "Preferiti"'):
        assert fav in body


def test_only_the_supervisor_may_connect(start_app):
    a = start_app(ui=True, TV7_UI_ALLOW="172.30.32.2")
    assert a.page("/")[0] == 403
    assert a.page("/status")[0] == 403, "the UI port does not serve the API to others"


def test_environment(app):
    c, body = app.page("/environment")
    e = json.loads(body)
    port = e["hdmi_ports"][0]
    assert c == 200 and port["name"] == "HDMI-A-1" and "1920x1080" in port["modes"] and len(port["modes"]) == 3, e
    assert (
        any(d["name"].startswith("pulse/") for d in e["audio"]["devices"]) and "HDMI-A-1" in e["choices"]["hdmi_port"]
    )
    assert "secret" not in body, "no token leak"


def test_settings_view(app):
    c, body = app.page("/settings?lang=de")
    s = json.loads(body)
    items = {i["key"]: i for i in s["items"]}
    assert c == 200 and s["labels"]["video_mode"]["name"] == "Bildauflösung" and s["can_save"] is True
    assert items["video_mode"]["restart"] is True and "api_token" not in items
    assert all(items[k]["nerd"] for k in ("video_mode", "hardware_decoding", "audio_device", "debug"))
    everyday = ("hdmi_port", "hdmi_disconnect", "audio_language", "start_volume", "audio_channels", "idle_stop")
    assert not any(items[k]["nerd"] for k in everyday), "the everyday settings are not nerd-only"
    unavailable = items["video_mode"]["unavailable"]
    assert "720p" in unavailable and "2160p" not in unavailable and "1080p" not in unavailable, "live choices"
    assert s["version"] == "9.9.9"
    assert app.get("/settings")[0] == 200, "/settings is also served on the API port"


def test_settings_validation(app):
    assert app.post("/settings", {"values": {}}, {"X-TV7-UI": "0"})[0] == 403, "POST needs the X-TV7-UI header"
    assert app.post("/settings", {"values": {"video_mode": "8k"}})[0] == 400
    assert app.post("/settings", {"values": {"listen": "0.0.0.0"}})[0] == 400, "option that does not exist (any more)"
    assert app.post("/settings", {"values": {"start_volume": "loud"}})[0] == 400, "wrong type"


def test_settings_save(app, world):
    sup = world.sup
    c, d = app.post("/settings", {"values": {"video_mode": "2160p", "audio_channels": "stereo", "audio_language": "fra",
                                             "start_volume": 90}})  # fmt: skip
    assert c == 200 and sup["options"]["video_mode"] == "2160p" and sup["auth"] == "Bearer tok", sup["options"]
    assert "api_token" not in sup["options"] and "subtitles" not in sup["options"], "options of older versions dropped"
    assert d["pending_restart"] == ["video_mode"], "restart-only setting is pending"
    assert set(d["applied_now"]) == {"audio_channels", "audio_language", "start_volume"}, "live ones are applied now"
    assert app.get("/status")[1]["pending_restart"] == ["video_mode"]
    app.post("/settings", {"values": {"audio_channels": "auto", "video_mode": "auto", "start_volume": 100,
                                      "audio_language": "auto"}})  # fmt: skip
    assert app.get("/status")[1]["pending_restart"] == [], "setting the old value again clears the flag"


def test_supervisor_rejection_and_restart(app, world):
    world.sup["reject"] = True
    try:
        c, d = app.post("/settings", {"values": {"deinterlace": False}})
    finally:
        world.sup["reject"] = False
    assert c == 502 and "invalid option" in d["error"], d
    before = world.sup["restarts"]
    c, d = app.post("/restart", {})
    time.sleep(1.2)
    assert c == 200 and world.sup["restarts"] == before + 1


def test_favorites(app):
    app.post("/favorites", {"favorites": []})
    assert json.loads(app.page("/favorites")[1])["favorites"] == []
    c, d = app.post("/favorites", {"favorites": ["pk-srf1", "srg-fhd:SRF 1 FHD", "pk-srf1"]})
    assert c == 200 and d["favorites"] == ["pk-srf1", "srg-fhd:SRF 1 FHD"], "de-duplicated, order kept"
    assert json.loads(app.page("/favorites")[1])["favorites"] == ["pk-srf1", "srg-fhd:SRF 1 FHD"], "favorites persist"
    assert app.post("/favorites", {"favorites": "SRF 1"})[0] == 400
    assert app.post("/favorites", {"favorites": [1, 2]})[0] == 400
    assert app.post("/favorites", {"favorites": []}, {"X-TV7-UI": "0"})[0] == 403, "saving needs the X-TV7-UI header"
    app.post("/favorites", {"favorites": []})


def test_dev_reload_version(app, world, start_app):
    """With TV7_DEV_RELOAD the version changes when the UI file changes (the page then reloads itself)."""
    ui_file = f"{world.tmp}/ui.html"
    with open(ui_file, "w") as f:
        f.write("<title>TV7 Player</title>")
    a = start_app(TV7_DEV_RELOAD="1", TV7_UI_FILE=ui_file)
    v1 = a.get("/status")[1]["version"]
    t = time.time() + 5
    os.utime(ui_file, (t, t))
    v2 = a.get("/status")[1]["version"]
    assert v1.startswith("9.9.9+") and v1 != v2, f"{v1} {v2}"
    assert app.get("/status")[1]["version"] == "9.9.9", "without TV7_DEV_RELOAD the plain app version"

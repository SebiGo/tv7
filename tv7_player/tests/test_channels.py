"""The SRG Full HD list next to TV7, Init7-only stream addresses, and channel logos."""

import hashlib
import os
import urllib.parse
import urllib.request


def test_srg_full_hd(world, start_app):
    a = start_app(TV7_SRG_FHD="true")
    c, d = a.get("/channels")
    srg = [x["name"] for x in d if x["list"] == "srg_fhd"]
    assert c == 200 and srg == ["SRF 1 FHD", "RTS 1 FHD"] and any(x["list"] == "tv7" for x in d), "a separate list"
    world.ready()
    c, d = a.get("/play?channel=SRF%201%20FHD&source=hls")
    assert c == 200 and world.state["loaded"].startswith("https://vtvapi03.sys.init7.net/"), d
    c, d = a.get("/play?channel=SRF%201%20FHD&source=multicast")
    assert c == 200 and world.state["loaded"] == "udp://233.50.230.1:5000?fifo_size=65536&overrun_nonfatal=1"
    c, d = a.get("/play?channel=RTS%201%20FHD&source=hls")
    assert c in (404, 502) and "evil" not in str(world.state["loaded"]), "SRG HLS entry from a foreign host is rejected"
    c, d = a.get("/play?channel=SRF%201")
    assert c == 200 and d["channel"] == "SRF 1", "the exact name 'SRF 1' still means the TV7 channel"


def test_tv7_and_srg_without_mpv_restart(world, start_app):
    """One mpv configuration: a TV7 channel (software) and an SRG Full HD channel (H.265 in hardware) need no restart."""
    a = start_app(TV7_SRG_FHD="true")
    world.ready(quit=0, hw=False)
    a.get("/play?channel=SRF%201")
    c, d = a.get("/play?channel=SRF%201%20FHD")
    a.get("/play?channel=SRF%201")
    a.get("/stop")
    assert c == 200 and world.state["quit"] == 0, d.get("log")


def test_srg_off(app):
    assert all(x["list"] == "tv7" for x in app.get("/channels")[1])


def test_logos(app, world):
    logo = app.get("/channels")[1][0]["logo"]
    r = urllib.request.urlopen(app.url("/icon?u=" + urllib.parse.quote(logo, safe="")), timeout=30)
    assert logo.endswith(".png") and r.status == 200 and r.read(4) == b"\x89PNG"
    assert r.headers["Cache-Control"].startswith("public")
    assert app.get("/icon?u=http%3A%2F%2Fevil.example%2Fx.png")[0] == 403, "only the Init7 logo prefixes"
    assert app.get("/icon?u=" + urllib.parse.quote(logo.rsplit(".", 1)[0] + ".svg", safe=""))[0] == 403, "only PNG/JPEG"
    assert hashlib.sha256(logo.encode()).hexdigest() in os.listdir(f"{world.tmp}/logos"), "cached on disk"

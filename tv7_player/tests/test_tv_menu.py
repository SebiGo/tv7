"""The TV overlays: technical info (/osd), menu, channel banner and remote keys (/key). The menu runs on its own instance
because its nerd mode stays switched on for that process. OSD overlay ids: 7 info, 8 menu, 9 banner, 10 menu background."""

import re
import time

import pytest

from fakes import App, wait_for


@pytest.fixture(scope="module")
def tv(world):
    world.ready()
    with App(world, ui=True) as a:
        a.get("/play?channel=SRF%201")
        yield a


def osd(world, i=None):
    """The last overlay command (with id i)."""
    return next((o for o in reversed(world.state.get("osd", [])) if i is None or o.get("id") == i), {})


def key(tv, k):
    return tv.get("/key?k=" + k)[1]


def test_tech_info(tv, world):
    c, d = tv.get("/osd?on=1&lang=de")
    time.sleep(0.3)
    last = osd(world)
    assert c == 200 and d["on"] is True and last.get("name") == "osd-overlay" and last.get("format") == "ass-events"
    assert "SRF 1" in last.get("data", "") and "Ausgabe" in last.get("data", ""), "the channel and German labels"
    assert tv.get("/status")[1].get("osd") is True
    n = len(world.state["osd"])
    time.sleep(1.5)
    assert len(world.state["osd"]) > n, "the overlay is refreshed while on"
    assert tv.get("/osd?on=yes")[0] == 400


def test_tech_info_follows_playback(tv, world):
    tv.get("/osd?on=1")
    tv.get("/stop")
    time.sleep(1.5)
    assert osd(world).get("format") == "none", "nothing playing: the overlay is removed (idle logo stays clean)"
    tv.get("/play?channel=SRF%201")
    time.sleep(1.5)
    assert osd(world).get("format") == "ass-events", "a channel starts again: the overlay comes back"
    c, d = tv.get("/osd?on=0")
    assert c == 200 and d["on"] is False and osd(world).get("format") == "none"
    assert tv.get("/status")[1].get("osd") is False


def test_menu_plays_the_next_channel(tv, world):
    world.ready()
    tv.get("/play?channel=SRF%201")
    d = key(tv, "ok")
    m = osd(world, 8)
    assert d["menu"] is True and d["tab"] == "channels" and m.get("format") == "ass-events"
    assert "SRF 1" in m["data"] and "SRF zwei" in m["data"] and r"\blur" in m["data"] and m.get("res_x") == 1920
    assert "1102" not in m["data"], "without nerd mode no channel numbers on the TV"
    before = world.state["loaded"]
    key(tv, "down")
    d = key(tv, "ok")
    wait_for(lambda: world.state["loaded"] != before and osd(world, 9).get("format") == "ass-events")
    assert d["menu"] is False and world.state["loaded"] != before and osd(world, 8).get("format") == "none"
    banner = osd(world, 9)
    assert banner.get("format") == "ass-events" and "SRF" in banner["data"], "the channel banner after a start"
    assert not any(n in banner["data"] for n in ("1102", "1104", "1106")), "no channel number (nerd mode off)"
    time.sleep(2.5)


def test_menu_audio_tab(tv, world):
    key(tv, "ok")
    d = key(tv, "right")
    assert d["tab"] == "audio" and "Deutsch" in osd(world, 8).get("data", "")
    world.state.pop("aid", None)
    key(tv, "ok")
    assert world.state.get("aid") == 1, "OK on an audio track selects it"
    key(tv, "left")
    d = key(tv, "back")
    assert d["menu"] is False and osd(world, 8).get("format") == "none", "back closes the menu"


def test_zap_and_digits(tv, world):
    before = world.state["loaded"]
    key(tv, "ch_up")
    assert wait_for(lambda: world.state["loaded"] != before), "channel up zaps to the next channel of the list"
    for k in "1104":
        key(tv, k)
    assert "1104_" in osd(world, 9).get("data", ""), "digits show the number in the banner"
    assert wait_for(lambda: str(world.state["loaded"]).startswith("udp://233.50.230.212"), 4), "1104 = SRF zwei"


def test_menu_closes_by_itself(tv, world):
    key(tv, "ok")
    time.sleep(4.5)
    assert osd(world, 8).get("format") == "none"
    assert tv.get("/key?k=power")[0] == 400, "unknown key"


def test_menu_settings_tab(tv, world):
    """OK switches a setting to its next value and saves it like the web UI; technical ones only in nerd mode."""
    sup = world.sup
    key(tv, "ok")
    d = key(tv, "left")
    m = osd(world, 8).get("data", "")
    assert d["tab"] == "settings" and "HDMI port" in m and "Picture resolution" not in m, "technical settings hidden"
    assert osd(world, 10).get("format") == "ass-events"
    for _ in range(15):
        key(tv, "down")  # the last entry: nerd mode (after stop and the technical info)
    m = osd(world, 8).get("data", "")
    assert m.rfind("Stop playback") < m.rfind("Technical info on the TV") < m.rfind("Nerd mode")
    key(tv, "ok")
    m = osd(world, 8).get("data", "")
    assert re.search(r"\\b1[^}]*\}Nerd mode", m), "nerd mode on: the selection stays on 'Nerd mode'"
    assert "DISPLAY" in m and "SYSTEM" not in m, "the options in one list, the TV entries in their own group"
    for _ in range(25):
        key(tv, "up")
    m = osd(world, 8).get("data", "")
    assert "Picture resolution" in m, "nerd mode shows the technical settings too"
    key(tv, "ok")
    m = osd(world, 8).get("data", "")
    assert (sup["options"] or {}).get("hdmi_port") == "HDMI-A-1" and "HDMI-A-1 · restart" in m, sup["options"]
    for _ in range(3):  # back to auto through the menu (HDMI-A-1 -> HDMI-A-2 -> auto)
        if (sup["options"] or {}).get("hdmi_port") == "auto":
            break
        key(tv, "ok")
    d = key(tv, "right")
    m = osd(world, 8).get("data", "")
    assert d["tab"] == "channels" and "1102" in m and "1104" in m, "nerd mode on: the channel list shows the numbers"
    key(tv, "left")
    assert (sup["options"] or {}).get("hdmi_port") == "auto", "OK cycles through the values back to the start"
    key(tv, "back")
    assert osd(world, 8).get("format") == "none" and osd(world, 10).get("format") == "none"

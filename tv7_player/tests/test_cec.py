"""HDMI-CEC (option cec) against a fake cec-ctl with two adapters; only cec1 has a display (physical address).
The mode file decides who holds the port: free | used (another program) | ours (an earlier start of the app)."""

import json
import os
import time
import urllib.request

import pytest

from fakes import App

RUNNING = {"state": "RUNNING", "components": ["http", "api", "media_player"]}
CEC_CTL = """#!/bin/bash
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
"""


@pytest.fixture(scope="module")
def cec_run(world):
    tmp = world.tmp
    for dev in ("cec0", "cec1"):
        open(f"{tmp}/{dev}", "w").close()
    with open(f"{tmp}/cec-ctl", "w") as f:
        f.write(CEC_CTL.format(tmp=tmp))
    os.chmod(f"{tmp}/cec-ctl", 0o755)

    def calls():
        with open(f"{tmp}/cec-calls") as f:
            return f.read()

    def run(mode, on, core=None, during=None, rx=False):
        """Start control.py with cec auto/off; core = Home Assistant's /api/config (None: not reachable); during(st)
        runs while the state is "waiting". Returns the CEC state (plus what was seen), the cec-ctl calls and the
        settings item."""
        with open(f"{tmp}/cec-mode", "w") as f:
            f.write(mode)
        open(f"{tmp}/cec-calls", "w").close()
        world.sup["core"] = core
        opts = world.options_file("options-cec.json", {"cec": "auto" if on else "off"})
        env = dict(TV7_OPTIONS=opts, TV7_CEC_CTL=f"{tmp}/cec-ctl", TV7_CEC_GLOB=f"{tmp}/cec[0-9]", TV7_CEC_CORE_POLL_S="0.2",
                   TV7_CEC_CORE_WAIT_S="1.5", TV7_CEC_AWAY_S="1", TV7_HDMI_POLL_S="0.2")  # fmt: skip
        with App(world, **env) as a:
            st, seen = {}, set()
            for _ in range(60):
                time.sleep(0.25)
                try:
                    st = a.get("/environment")[1]["cec"]
                except Exception:
                    continue
                seen.add(st["state"])
                if st["state"] == "waiting" and during:
                    during(st)
                    during = None
                if st["state"] not in ("off", "waiting") or not on and "--clear" in calls():
                    break
            item = next(x for x in a.get("/settings")[1]["items"] if x["key"] == "cec")
            st["seen"] = sorted(seen)
            if st["state"] == "active":  # the message receiver runs in the background
                time.sleep(0.8)
                st["nerd_log"] = a.get("/nerd")[1]["cec"]["log"]
                st["support"] = a.get("/support")[1]["text"]
                n_as = calls().count("--active-source")
                urllib.request.urlopen(a.url("/play?channel=SRF%201"), timeout=30).read()
                time.sleep(0.5)
                st["active_after_play"] = calls().count("--active-source") - n_as
                if rx:  # CEC messages from the TV while a channel plays

                    def send(text, wait):
                        with open(f"{tmp}/cec-rx", "w") as f:
                            f.write(text)
                        open(f"{tmp}/cec-go", "w").close()
                        time.sleep(wait)
                        return json.load(urllib.request.urlopen(a.url("/status"), timeout=10))

                    st["rx"] = [
                        send("Received from TV to all (0 to 15): STANDBY (0x36)\n", 1.0),
                        send("Received from TV to all (0 to 15): SET_STREAM_PATH (0x86):\n\tphys-addr: 3.0.0.0\n", 2.5),
                        send(
                            "Received from Playback Device 1 to all (4 to 15): ACTIVE_SOURCE (0x82):\n\tphys-addr: 3.4.0.0\n",
                            0.4,
                        ),
                    ]
                    time.sleep(1.5)
                    st["rx"].append(a.get("/status")[1])
            return st, calls(), item

    return run


def test_active(world, cec_run):
    """cec auto, no HDMI-CEC integration, port free: registers as TV7 on the adapter with a display (cec1)."""
    world.ready()
    world.state["osd"] = []
    st, calls, item = cec_run("free", True, core=RUNNING, rx=True)
    assert st["state"] == "active" and st["device"].endswith("cec1"), st
    assert "cec1 --playback --osd-name=TV7" in calls and "cec1 -S" in calls, calls
    assert [d["name"] for d in st["devices"]] == ["Beamer", None, "AVR-X2200W"] and st["devices"][0][
        "vendor"
    ] == "0x00e091 (LG)"
    assert st["topology"][-1].strip() == "3.1.0.0: Playback Device 1"
    assert "locked" not in item, "the option is not greyed out when the app uses CEC"

    log = "\n".join(st.get("nerd_log", []))
    assert "-W -w ---" in log and " -m " not in log, "received through cec-ctl -W"
    assert "USER_CONTROL_PRESSED" in log and "ui-cmd: up (0x01)" in log, "key press logged in nerd mode"
    assert "cec1 --to=0 --report-power-status=pwr-state=on" in calls, "power status answered to the asking TV"
    assert "cec1 --active-source=phys-addr=3.0.0.0" in calls, "active source confirmed when the TV switches to the app"
    assert st.get("active_after_play", 0) >= 1, "a channel start announces the app as the active source"
    assert "3.0.0.0: Audio System" in st["support"] and "| 3.0.0.0 |" in st["support"], "CEC addresses are not masked"
    assert any(o.get("id") == 8 and o.get("format") == "ass-events" for o in world.state["osd"]), (
        "a CEC key opens the menu"
    )

    standby, back, other, later = st["rx"]
    assert not standby.get("playing") and (standby.get("autostopped") or {}).get("reason") == "cec", "TV standby: stop"
    assert back.get("playing") is True and back.get("channel") == "SRF 1", "the TV shows TV7 again: resume"
    assert other.get("playing") is True, "another source: still playing during the grace time"
    assert not later.get("playing") and (later.get("autostopped") or {}).get("reason") == "cec", "then stopped"


def test_port_used_by_another_program(cec_run):
    st, calls, item = cec_run("used", True, core=RUNNING)
    assert st["state"] == "in_use" and "--playback" not in calls and "CEC Adapter" in st["detail"], st
    assert item.get("locked") == "in_use", "option greyed out"


def test_own_registration_of_an_earlier_start(cec_run):
    st, calls, item = cec_run("ours", True, core=RUNNING)
    assert st["state"] == "active", st


def test_cec_off(cec_run):
    st, calls, item = cec_run("ours", False)
    assert "cec1 --clear" in calls and "--playback" not in calls and st.get("state") == "off", (
        "own registration removed"
    )
    st, calls, item = cec_run("used", False)
    assert "--clear" not in calls and "--playback" not in calls, "another program's registration stays untouched"


def test_home_assistant_cec_integration(cec_run):
    st, calls, item = cec_run("free", True, core={"state": "RUNNING", "components": ["http", "hdmi_cec"]})
    assert st["state"] == "ha_integration" and "--playback" not in calls and item.get("locked") == "ha_integration", st


def test_waits_for_home_assistant(world, cec_run):
    """Home Assistant still starting: the app waits, then sees the integration loaded meanwhile."""
    loaded = {"state": "RUNNING", "components": ["http", "hdmi_cec"]}
    st, calls, item = cec_run("free", True, core={"state": "STARTING", "components": ["http"]},
                              during=lambda _: world.sup.update(core=loaded))  # fmt: skip
    assert "waiting" in st["seen"] and st["state"] == "ha_integration" and "--playback" not in calls, st


def test_home_assistant_not_reachable(cec_run):
    st, calls, item = cec_run("free", True, core=None)
    assert st["state"] == "active" and "cec1 --playback" in calls, "after the wait only the port decides"

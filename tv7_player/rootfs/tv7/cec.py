"""HDMI-CEC: whether the port is free, registration as "TV7", the received messages and the answers to the TV.

What the TV tells goes to `handlers` (set at start in control.py): remote control keys, standby, and which physical
address the TV shows. This module only talks to the bus; what playback does about it is in tv7/player.py."""

import glob
import re
import subprocess
import threading
import time

from tv7 import config, supervisor

CEC_NAME = "TV7"  # OSD name: how the app shows up in the TV's/projector's device list
cec_state = {"state": "off", "device": None, "detail": None, "devices": [], "topology": []}
CEC_LOCKED = ("ha_integration", "in_use")  # states in which the web UI greys out the option


def ha_cec_integration():
    """Wait until Home Assistant Core has started (its integrations are loaded), then tell whether its HDMI-CEC
    integration runs. None: Core not reachable (no Supervisor, or not started within config.CEC_CORE_WAIT_S)."""
    end = time.time() + config.CEC_CORE_WAIT_S
    while True:
        cfg = supervisor.core_config()
        if cfg and str(cfg.get("state", "RUNNING")).upper() == "RUNNING":
            return "hdmi_cec" in (cfg.get("components") or [])
        if not supervisor.available() or time.time() >= end:
            return None
        time.sleep(config.CEC_CORE_POLL_S)


def _cec(dev, *args, timeout=20):
    r = subprocess.run([config.CEC_CTL, "-d", dev, *args], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def _cec_field(text, name):
    m = re.search(rf"^\s*{re.escape(name)}\s*:\s*(.+?)\s*$", text or "", re.M)
    return m[1].strip("'") if m else None


def parse_cec_topology(text):
    """`cec-ctl -S`: the devices (type, OSD name, vendor, physical address, power) and the topology lines."""
    devices = []
    for block in re.split(r"System Information for device ", text)[1:]:
        m = re.match(r"(\d+) \(([^)]*)\)", block)
        name = _cec_field(block, "OSD Name")
        # cec-ctl prints the transmit status when the device did not answer
        if name and re.search(r"\bTimeout\b|^Tx\b", name):
            name = None
        devices.append(
            {
                "address": m[1] if m else None,
                "type": m[2] if m else None,
                "name": name,
                "vendor": _cec_field(block, "Vendor ID"),
                "physical": _cec_field(block, "Physical Address"),
                "power": _cec_field(block, "Power Status"),
            }
        )
    topo = text.split("Topology:", 1)[1].strip("\n").splitlines() if "Topology:" in text else []
    return devices, [t.expandtabs(4).rstrip() for t in topo if t.strip()]


CEC_LOG_LINES = 300
# a receiver that ends this fast did not work: try the next one
CEC_MON_FAIL_S = 3.0
_cec_log = []
_cec_log_lock = threading.Lock()


def cec_log_add(line):
    with _cec_log_lock:
        _cec_log.append(line)
        del _cec_log[:-CEC_LOG_LINES]


def cec_log():
    with _cec_log_lock:
        return list(_cec_log)


def cec_monitor(dev):
    """Log the CEC messages the app receives (remote control keys, routing, power) for nerd mode and the support info,
    and act on them (cec_parse). "cec-ctl -W" gets the messages to the app and the broadcasts (seeing all traffic would
    need CAP_NET_ADMIN). If it ends later it is started again; if it ends at once, it does not work here."""
    args = ["-W", "-w"]
    while True:
        cec_log_add(f"--- {config.CEC_CTL} -d {dev} {' '.join(args)} ---")
        t0 = time.time()
        try:
            proc = subprocess.Popen(
                [config.CEC_CTL, "-d", dev, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            for line in proc.stdout:
                if line.strip():
                    cec_log_add(line.rstrip().expandtabs(4))
                    cec_parse(line)
            code = proc.wait()
        except Exception as e:
            code = None
            cec_log_add(f"failed: {e}")
        if time.time() - t0 < CEC_MON_FAIL_S:
            cec_log_add(f"--- ended at once (exit code {code}) ---")
            config.log_line("CEC: no way to receive CEC messages (see the CEC log in nerd mode)")
            return
        cec_log_add(f"--- ended (exit code {code}), starting again ---")
        time.sleep(5)


def cec_setup(enabled):
    """Checked once at app start. Option cec off: leave CEC alone (and remove the app's own registration of an earlier
    start). auto: wait for Home Assistant Core; if its HDMI-CEC integration runs, or another program registered on the
    port, stay out. Otherwise register as playback device "TV7" on the adapter of the connected HDMI port and read which
    devices are on the bus."""
    devs = sorted(glob.glob(config.CEC_GLOB))

    def read_infos():
        out = []
        for d in devs:
            try:
                out.append((d, _cec(d)[1]))
            except Exception as e:
                out.append((d, None))
                config.log_line(f"CEC: {d}: {e}")
        return out

    if not enabled:
        infos = read_infos()
        for d, info in infos:
            if info and _cec_field(info, "OSD Name") == CEC_NAME:
                try:
                    _cec(d, "--clear")
                    config.log_line(f"CEC: option off, registration of the app on {d} removed")
                except Exception as e:
                    config.log_once("CEC: removing the app's registration", e)
        cec_state.update(state="off", device=None, detail=None, devices=[], topology=[])
        return
    if not devs:
        cec_state.update(state="no_device", detail="no /dev/cec* device in the app")
        config.log_line("CEC: no CEC device available")
        return
    cec_state.update(state="waiting", detail="waiting for Home Assistant to finish starting")
    ha = ha_cec_integration()
    if ha:
        cec_state.update(state="ha_integration", detail="Home Assistant's HDMI-CEC integration is active")
        config.log_line("CEC: Home Assistant's HDMI-CEC integration is active; the app leaves CEC alone")
        return
    if ha is None:
        config.log_line("CEC: Home Assistant not reachable; only the CEC port itself is checked")
    infos = read_infos()  # after the wait: the port as it is now
    usable = [(d, i) for d, i in infos if i]
    if not usable:
        cec_state.update(state="error", detail=f"{config.CEC_CTL} failed on {', '.join(devs)}")
        return
    # The adapter of the connected port has a physical address (f.f.f.f = nothing connected).
    dev, info = next(
        ((d, i) for d, i in usable if (_cec_field(i, "Physical Address") or "f.f.f.f") != "f.f.f.f"), usable[0]
    )
    mask, osd = _cec_field(info, "Logical Address Mask") or "0x0000", _cec_field(info, "OSD Name") or ""
    try:
        used = int(mask, 16) != 0 and osd != CEC_NAME
    except ValueError:
        used = False
    if used:
        cec_state.update(
            state="in_use",
            device=dev,
            detail=f"already registered as '{osd}' (logical address mask {mask})",
            devices=[],
            topology=[],
        )
        config.log_line(
            f"CEC: {dev} is already used by another program ('{osd}', e.g. Home Assistant's HDMI-CEC integration); "
            "the app leaves it alone"
        )
        return
    code, out = _cec(dev, "--playback", f"--osd-name={CEC_NAME}")
    if code:
        cec_state.update(state="error", device=dev, detail=(out.strip().splitlines() or ["registration failed"])[-1])
        config.log_line(f"CEC: registration on {dev} failed: {cec_state['detail']}")
        return
    code, out = _cec(dev, "-S", timeout=60)
    devices, topo = parse_cec_topology(out)
    cec_state.update(
        state="active",
        device=dev,
        phys=_cec_field(info, "Physical Address"),
        detail=f"physical address {_cec_field(info, 'Physical Address') or '?'}",
        devices=devices,
        topology=topo,
    )
    config.log_line(
        f"CEC: registered on {dev} as '{CEC_NAME}'; devices: "
        + (", ".join(f"{x['type']} '{x['name']}'" for x in devices) or "none answered")
    )
    threading.Thread(target=cec_monitor, args=(dev,), daemon=True).start()


CEC_KEYS = {
    0x00: "ok",
    0x01: "up",
    0x02: "down",
    0x03: "left",
    0x04: "right",
    0x0D: "back",
    0x30: "ch_up",
    0x31: "ch_down",
    0x35: "info",
    0x44: "play",
    0x45: "stop",
    0x46: "pause",
    **{0x20 + d: str(d) for d in range(10)},
}
KEYS = set(CEC_KEYS.values())
_cec_rx = {"msg": None}

# key(name): a remote control key; standby(): the TV switched to standby; shown(ours): the TV switched to a source, ours
# is True for the app's own address; playing(): whether a channel plays (the TV asks who the active source is).
handlers = {"key": lambda k: None, "standby": lambda: None, "shown": lambda ours: None, "playing": lambda: False}


def cec_send(*args):
    """Send a CEC message with cec-ctl (in the background; the answer is logged with the CEC messages)."""
    dev = cec_state.get("device")
    if not dev:
        return

    def run():
        try:
            code, out = _cec(dev, *args, timeout=10)
            cec_log_add(
                f"Sent: {' '.join(args)}"
                + ("" if code == 0 else f" (failed: {(out.strip().splitlines() or ['?'])[-1]})")
            )
        except Exception as e:
            cec_log_add(f"Sent: {' '.join(args)} (failed: {e})")

    threading.Thread(target=run, daemon=True).start()


def cec_active_source():
    """Announce the app as the active source (CEC "One Touch Play"), as a playback device does when it starts
    playing."""
    if cec_state.get("state") == "active" and cec_state.get("phys"):
        cec_send(f"--active-source=phys-addr={cec_state['phys']}")


def cec_parse(line):
    """cec-ctl's output of received messages: "Received from <dev> to <dev> (<from> to <to>): <MESSAGE> (0x..)" and
    indented parameters. Remote control keys (USER_CONTROL_PRESSED, "ui-cmd: <name> (0x..)") go to the TV menu. Answered
    like a playback device: the power status (the TV asks for it regularly), and the active source when the TV switches
    to the app's address."""
    m = re.search(r"Received from .*\((\d+) to (\d+)\): ([A-Z_]+)", line)
    if m:
        _cec_rx["msg"] = m[3]
        if m[3] == "GIVE_DEVICE_POWER_STATUS":
            cec_send(f"--to={m[1]}", "--report-power-status=pwr-state=on")
        elif m[3] == "STANDBY" and m[1] == "0":  # from the TV (to all or to the app)
            handlers["standby"]()
        elif m[3] == "REQUEST_ACTIVE_SOURCE" and handlers["playing"]():  # asked who plays: the app, if a channel runs
            cec_active_source()
        return
    if _cec_rx["msg"] in ("SET_STREAM_PATH", "ACTIVE_SOURCE", "ROUTING_CHANGE"):
        pm = re.search(r"^\s*(?:new-)?phys-addr:\s*([0-9a-fA-F.]+)", line)
        if pm:
            msg, _cec_rx["msg"] = _cec_rx["msg"], None
            if msg == "SET_STREAM_PATH" and cec_state.get("phys") and pm[1] == cec_state["phys"]:
                cec_send(f"--active-source=phys-addr={pm[1]}")
            handlers["shown"](bool(cec_state.get("phys")) and pm[1] == cec_state["phys"])
        return
    m = re.search(r"ui-cmd:.*\((0x[0-9a-fA-F]+)\)", line)
    if m and _cec_rx["msg"] == "USER_CONTROL_PRESSED":
        _cec_rx["msg"] = None
        key = CEC_KEYS.get(int(m[1], 16))
        if key:
            try:
                handlers["key"](key)
            except Exception as e:
                config.log_line(f"Remote control key {key}: {e}")

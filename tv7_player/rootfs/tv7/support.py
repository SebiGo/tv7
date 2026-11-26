"""Support information for a GitHub issue (Markdown), with everything confidential masked."""

import ipaddress
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from tv7 import config, display, init7, player, settings, system

MASK = "****"
_SECRET_RE = re.compile(
    r'(?i)\b(api_token|token|bearer|authorization|password|passwd|secret|api_key|apikey)\b(["\']?\s*[=:]\s*["\']?|\s+)([^\s"\',&]+)'
)
_QUERY_RE = re.compile(r'((?:https?|rtsp|rtmp)://[^\s?#"\'<>]+)\?[^\s"\'<>]*')
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_BEARER_RE = re.compile(r'(?i)\bbearer\s+[^\s"\',&]+')
_IPV6_MAC_RE = re.compile(
    r"(?i)(?<![\w:])(?=[0-9a-f:]*::|(?:[0-9a-f]{1,4}:){3})[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,7}(?![\w:])"
)


def redact(text):
    """Mask what does not belong into a public issue: tokens/passwords, URL query strings (may carry session tokens),
    unicast IPv4 addresses (multicast group addresses of the channels and 127.0.0.1/0.0.0.0 stay; HDMI-CEC physical addresses such
    as 1.1.0.0, four single digits, stay too), IPv6 and MAC addresses."""

    def ip(m):
        if all(len(x) == 1 for x in m.group(0).split(".")):
            return m.group(0)
        try:
            a = ipaddress.ip_address(m.group(0))
        except ValueError:
            return m.group(0)
        return m.group(0) if a.is_multicast or a.is_loopback or a.is_unspecified else MASK

    text = _BEARER_RE.sub("Bearer " + MASK, text)
    text = _SECRET_RE.sub(lambda m: m.group(1) + m.group(2) + (m.group(3) if m.group(3) == MASK else MASK), text)
    text = _QUERY_RE.sub(lambda m: m.group(1) + "?" + MASK, text)
    text = _IPV4_RE.sub(ip, text)
    return _IPV6_MAC_RE.sub(MASK, text)


def supervisor_info():
    """Versions of Home Assistant OS, Core and Supervisor plus machine type (empty outside Home Assistant)."""
    if not config.SUPERVISOR_TOKEN:
        return {}
    try:
        req = urllib.request.Request(
            config.SUPERVISOR + "/info", headers={"Authorization": f"Bearer {config.SUPERVISOR_TOKEN}"}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.load(r).get("data", {})
        return {k: d.get(k) for k in ("hassos", "homeassistant", "supervisor", "machine", "arch", "operating_system")}
    except Exception:
        return {}


APP_LOG_LINES = int(os.environ.get("TV7_APP_LOG_LINES", "120"))


def app_log():
    """The last lines of this app's own log (the start of mpv, its warnings; with debug on its detailed log) from the Supervisor."""
    if not config.SUPERVISOR_TOKEN:
        return []
    try:
        req = urllib.request.Request(
            config.SUPERVISOR + "/addons/self/logs",
            headers={
                "Authorization": f"Bearer {config.SUPERVISOR_TOKEN}",
                "Accept": "text/plain",
                "Range": f"entries=:-{APP_LOG_LINES}:",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            text = r.read(400000).decode("utf-8", "replace")
        text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)  # colour codes
        return text.splitlines()[-APP_LOG_LINES:]
    except Exception:
        return []


def support_text():
    """Everything a bug report needs, as Markdown that fits the repository's issue template; secrets masked."""
    if system.system_load().get("total") is None:  # CPU load needs two samples
        time.sleep(0.6)
    n, env, sup, alog = system.nerd(), system.environment(), supervisor_info(), app_log()
    v, f, a, o, sy = n["video"], n["frames"], n["audio"], n["output"], n["system"]
    model = (
        system._read("/proc/device-tree/model") or system._read("/sys/firmware/devicetree/base/model") or ""
    ).replace("\x00", "") or None
    opts = env.get("options", {})

    def val(x):
        if x is None or x == "" or x == []:
            return "–"
        if isinstance(x, bool):
            return "yes" if x else "no"
        if isinstance(x, float):
            return f"{x:g}"
        if isinstance(x, (list, tuple)):
            return ", ".join(str(i) for i in x)
        return str(x).replace("|", "\\|")

    def table(rows):
        return "\n".join(["| | |", "|---|---|"] + [f"| {k} | {val(x)} |" for k, x in rows])

    def ts(t):
        return time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(t)) if t else None

    def kbit(b):
        return f"{b / 1000:.0f} kbit/s" if b else None

    log = n["log"][-60:]
    parts = [
        "## Problem/Motivation",
        "",
        "> (Why the issue was filed)",
        "",
        "## Expected behavior",
        "",
        "> (What you expected to happen)",
        "",
        "## Actual behavior",
        "",
        "> (What actually happened)",
        "",
        "## Steps to reproduce",
        "",
        "> (How can someone else make/see it happen)",
        "",
        "## System",
        "",
        table(
            [
                ("TV7 Player", config.VERSION),
                ("Home Assistant OS", sup.get("hassos") or sup.get("operating_system")),
                ("Home Assistant Core", sup.get("homeassistant")),
                ("Supervisor", sup.get("supervisor")),
                ("Machine / arch", " / ".join(x for x in (sup.get("machine"), sup.get("arch")) if x) or None),
                ("Device", model),
                ("Kernel", os.uname().release),
                ("mpv", n["mpv"]["version"]),
                ("FFmpeg", n["mpv"]["ffmpeg"]),
                ("H.265 hardware decoder", "yes" if display.hw_available() else "no"),
                (
                    "Video output choice",
                    (lambda v: f"{v['vo']}" + (" (pending: no display at start)" if v["pending"] == "yes" else ""))(
                        display.video_state()
                    ),
                ),
                ("Report created", ts(time.time())),
                ("App running for", f"{(time.time() - config.STARTED) / 3600:.1f} h"),
            ]
        ),
        "",
        "## Playback",
        "",
        table(
            [
                ("Playing", "yes" if n["playing"] else "no"),
                ("Channel", n["channel"]),
                ("Source", n["source"]),
                ("Stream URL", n["url"]),
                ("Container", n["format"]),
                ("Video codec", v["codec"]),
                ("Decoder", f"{v['hwdec_current'] or 'no'} (hwdec={v['hwdec'] or '–'})"),
                ("Pixel format", v["pixelformat"]),
                ("Stream resolution", f"{v['w']}x{v['h']}" if v["w"] else None),
                ("Frame rate", v["fps"]),
                ("Video bitrate", kbit(v["bitrate"])),
                ("Deinterlace", v["deinterlace"]),
                ("Filters", v["filters"]),
                (
                    "Dropped frames (output / decoder)",
                    f"{f['dropped_vo']} / {f['dropped_decoder']}" if f["dropped_vo"] is not None else None,
                ),
                (
                    "Delayed / mistimed frames",
                    f"{f['delayed']} / {f['mistimed']}" if f["delayed"] is not None else None,
                ),
                ("A/V offset", f"{f['avsync'] * 1000:.1f} ms" if f["avsync"] is not None else None),
                ("Audio codec", a["codec_name"]),
                (
                    "Audio decoded",
                    " ".join(
                        str(x) for x in (a["format"], a["samplerate"] and f"{a['samplerate']} Hz", a["channels"]) if x
                    )
                    or None,
                ),
                (
                    "Audio to the device",
                    " ".join(
                        str(x)
                        for x in (
                            a["out_format"],
                            a["out_samplerate"] and f"{a['out_samplerate']} Hz",
                            a["out_channels"],
                        )
                        if x
                    )
                    or None,
                ),
                ("Audio bitrate", kbit(a["bitrate"])),
                ("Audio device / output", f"{a['device'] or '–'} / {a['ao'] or '–'}"),
            ]
        ),
        "",
        "## Last channel start",
        "",
        table(
            [
                ("When", ts(player.last_start.get("t"))),
                ("Channel", player.last_start.get("channel")),
                ("Requested source", player.last_start.get("requested")),
                (
                    "Result",
                    None
                    if not player.last_start
                    else ("ok via " + str(player.last_start.get("source")))
                    if player.last_start.get("ok")
                    else "failed",
                ),
                (
                    "Duration",
                    f"{player.last_start['seconds']:g} s" if player.last_start.get("seconds") is not None else None,
                ),
            ]
        ),
        "",
        *(["```", *player.last_start.get("log", []), "```", ""] if player.last_start.get("log") else []),
        "## Channel lists",
        "",
        table(
            [
                ("TV7 channels", sum(1 for c in init7._cache["data"] if c.get("list") == "tv7")),
                ("SRG Full HD channels", len(init7._cache["srg"]) if init7.SRG_FHD else "off"),
                (
                    "Last successful sync (TV7 / SRG)",
                    f"{ts(init7._sync['tv7_ok'])} / {ts(init7._sync['srg_ok']) if init7.SRG_FHD else 'off'}",
                ),
                ("Last attempt", ts(init7._sync["tried"])),
                ("Cache time", f"{init7.CACHE_S} s"),
                ("Last error (TV7)", init7._sync["tv7_error"]),
                ("Last error (SRG)", init7._sync["srg_error"]),
            ]
        ),
        "",
        "## Display output",
        "",
        table(
            [
                ("Video output", o["vo"]),
                ("Output", f"{o['w']}x{o['h']} @ {o['hz']:g} Hz" if o["w"] and o["hz"] else None),
                ("DRM device / connector", f"{o['drm_device'] or '–'} / {o['drm_connector'] or 'auto'}"),
                (
                    "DRM mode",
                    o["drm_mode"] + (f" (override {o['drm_mode_override']})" if o["drm_mode_override"] else "")
                    if o["drm_mode"]
                    else o["drm_mode_override"],
                ),
                ("Planes (draw / video)", f"{o['draw_plane'] or '–'} / {o['video_plane'] or '–'}"),
                ("Hardware interop", o["hwdec_interop"]),
                *[
                    (
                        f"Plane {x['id']} ({x.get('type', '?')})",
                        ", ".join(
                            f"{k} {x[k]}"
                            for k in ("zpos", "alpha", "pixel blend mode", "COLOR_ENCODING", "COLOR_RANGE")
                            if k in x
                        ),
                    )
                    for x in o.get("planes") or []
                ],
                ("Stopped because HDMI is disconnected", player.hdmi_stopped.get("name")),
                ("Stop without operation (idle_stop)", settings.current_values().get("idle_stop")),
                (
                    "Last automatic stop",
                    f"{player.autostopped['reason']}: {player.autostopped['channel']} at {ts(player.autostopped['t'])}"
                    if player.autostopped
                    else None,
                ),
            ]
        ),
        "",
        "## HDMI-CEC",
        "",
        f"State: {env['cec']['state']}"
        + (
            f" ({env['cec']['device']}, {env['cec']['detail']})"
            if env["cec"]["device"]
            else (f" ({env['cec']['detail']})" if env["cec"]["detail"] else "")
        ),
        "",
        *(
            [
                "| Address | Type | Name | Vendor | Physical | Power |",
                "|---|---|---|---|---|---|",
                *[
                    f"| {d['address']} | {d['type']} | {d['name'] or '–'} | {d['vendor'] or '–'} | {d['physical'] or '–'} | {d['power'] or '–'} |"
                    for d in env["cec"]["devices"]
                ],
                "",
            ]
            if env["cec"]["devices"]
            else []
        ),
        *(["```", *env["cec"]["topology"], "```", ""] if env["cec"]["topology"] else []),
        "## Environment",
        "",
        "| HDMI port | Status | Modes |",
        "|---|---|---|",
        *[
            f"| {p['name']} | {p['status']} | {val(env['drm_modes'].get(p['name']) or p['modes'])} |"
            for p in env["hdmi_ports"]
        ],
        *([] if env["hdmi_ports"] else ["| – | – | – |"]),
        "",
        "Audio devices (mpv): " + (", ".join(f"`{d['name']}`" for d in env["audio"]["devices"]) or "–"),
        "",
        "PulseAudio sinks: " + (", ".join(f"`{x['name']}` ({x['state']})" for x in env["audio"]["pulse_sinks"]) or "–"),
        "",
        "ALSA playback: " + ("; ".join(system.alsa_status()) or "–"),
        "",
        "/dev/dri: " + (", ".join(system.dri_devices()) or "–"),
        "",
        "System: "
        + ", ".join(
            x
            for x in (
                sy.get("total") is not None and f"CPU {sy['total']:g} %",
                sy.get("mpv") is not None and f"mpv {sy['mpv']:g} % of one core",
                sy.get("cores") and f"{sy['cores']} cores",
                sy.get("temp_c") is not None and f"{sy['temp_c']:g} °C",
                sy["clock"].get("mhz")
                and f"{sy['clock']['mhz']}/{sy['clock']['max_mhz']} MHz ({sy['clock']['governor']})",
                sy["memory"].get("available_mib") is not None
                and f"{sy['memory']['available_mib']}/{sy['memory']['total_mib']} MiB free",
            )
            if x
        ),
        "",
        "## Options",
        "",
        "Effective options (`/data/options.json`):",
        "",
        "```json",
        json.dumps(opts, indent=2, sort_keys=True),
        "```",
        "",
        "Saved in the web UI, waiting for a restart: "
        + (", ".join(f"`{k}`" for k in settings.pending_restart()) or "none"),
        "",
        f"<details><summary>mpv log (last {len(log)} messages)</summary>",
        "",
        "```",
        *(log or ["(no messages)"]),
        "```",
        "",
        "</details>",
        "",
        *(
            [
                f"<details><summary>CEC messages (last {len(n['cec']['log'])} lines)</summary>",
                "",
                "```",
                *n["cec"]["log"],
                "```",
                "",
                "</details>",
                "",
            ]
            if n["cec"]["log"]
            else []
        ),
        f"<details><summary>App log (last {len(alog)} lines; turn on the debug option and restart for the full device diagnosis)</summary>",
        "",
        "```",
        *(alog or ["(not available)"]),
        "```",
        "",
        "</details>",
        "",
    ]
    return redact("\n".join(parts))

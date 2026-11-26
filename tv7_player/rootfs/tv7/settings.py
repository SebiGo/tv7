"""Settings: editable in the web UI and the TV menu, stored as the app's options by the Supervisor."""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from tv7 import cec, config, display, mpvclient, supervisor


def _c(*v):
    return list(v)


# key: type (choice|bool|int|str), choices, restart (needs an app restart), group, nerd (technical: the web UI shows it only in nerd mode or when it differs from the default)
SETTINGS = [
    {
        "key": "hdmi_port",
        "type": "choice",
        "choices": _c("auto", "HDMI-A-1", "HDMI-A-2"),
        "group": "video",
        "restart": True,
        "nerd": False,
    },
    {
        "key": "hdmi_disconnect",
        "type": "choice",
        "choices": _c("resume", "stop", "keep"),
        "group": "video",
        "restart": False,
        "nerd": False,
    },
    {"key": "cec", "type": "choice", "choices": _c("auto", "off"), "group": "video", "restart": True, "nerd": False},
    {
        "key": "video_output",
        "type": "choice",
        "choices": _c("auto", "drm", "gpu"),
        "group": "video",
        "restart": True,
        "nerd": True,
    },
    {
        "key": "video_mode",
        "type": "choice",
        "choices": _c("auto", "highest", "2160p", "1080p", "720p"),
        "group": "video",
        "restart": True,
        "nerd": True,
    },
    {
        "key": "video_refresh",
        "type": "choice",
        "choices": _c("auto", "50", "60"),
        "group": "video",
        "restart": True,
        "nerd": True,
    },
    {"key": "deinterlace", "type": "bool", "group": "video", "restart": False, "nerd": True},
    {
        "key": "hardware_decoding",
        "type": "choice",
        "choices": _c("auto", "no"),
        "group": "video",
        "restart": True,
        "nerd": True,
    },
    {
        "key": "decode_speed",
        "type": "choice",
        "choices": _c("quality", "fast"),
        "group": "video",
        "restart": True,
        "nerd": True,
    },
    {
        "key": "audio_output",
        "type": "choice",
        "choices": _c("auto", "pulseaudio", "alsa"),
        "group": "audio",
        "restart": True,
        "nerd": True,
    },
    {"key": "audio_device", "type": "str", "group": "audio", "restart": False, "nerd": True},
    {
        "key": "audio_language",
        "type": "choice",
        "choices": _c("auto", "deu", "fra", "ita", "eng", "roh"),
        "group": "audio",
        "restart": False,
        "nerd": False,
    },
    {
        "key": "audio_channels",
        "type": "choice",
        "choices": _c("auto", "stereo"),
        "group": "audio",
        "restart": False,
        "nerd": False,
    },
    {"key": "start_volume", "type": "int", "min": 0, "max": 130, "group": "audio", "restart": False, "nerd": False},
    {
        "key": "idle_stop",
        "type": "choice",
        "choices": _c("off", "60", "120", "180", "240", "480"),
        "group": "system",
        "restart": False,
        "nerd": False,
    },
    {"key": "debug", "type": "bool", "group": "system", "restart": True, "nerd": True},
]
BY_KEY = {x["key"]: x for x in SETTINGS}
DEFAULTS = {
    "hdmi_port": "auto",
    "hdmi_disconnect": "resume",
    "video_output": "auto",
    "video_mode": "auto",
    "video_refresh": "auto",
    "deinterlace": True,
    "hardware_decoding": "auto",
    "decode_speed": "quality",
    "audio_output": "auto",
    "audio_device": "",
    "audio_language": "auto",
    "audio_channels": "auto",
    "cec": "auto",
    "start_volume": 100,
    "idle_stop": "off",
    "debug": False,
}
_applied = {}  # what the running process actually uses (restart-only settings keep their start value)
_saved = {}  # values saved through the UI (the options file may lag behind)


def read_options():
    try:
        return json.load(open(config.OPTIONS_FILE))
    except Exception:
        return {}


def current_values():
    o = {**DEFAULTS, **read_options(), **_saved}
    return {k: o.get(k, DEFAULTS[k]) for k in BY_KEY}


def applied_value(key):
    """The value the running process uses (a restart-only setting keeps its value from the start)."""
    return _applied.get(key, current_values()[key])


def pending_restart(values=None):
    values = values or current_values()
    return [k for k, spec in BY_KEY.items() if spec["restart"] and k in _applied and _applied[k] != values.get(k)]


def apply_live(key, val):
    """Apply a setting to the running app/mpv where possible. Returns True if it took effect now."""
    try:
        if key == "deinterlace":
            _applied[key] = val
            display.update_deinterlace(val)
        elif key == "audio_language":
            mpvclient.mpv("set_property", "alang", "" if val == "auto" else f"{val},eng")
        elif key == "audio_channels":
            mpvclient.mpv("set_property", "audio-channels", "stereo" if val == "stereo" else "auto-safe")
        elif key == "start_volume":
            mpvclient.mpv("set_property", "volume", float(val))
        elif key in ("hdmi_disconnect", "idle_stop"):
            pass  # read by the watcher on every check
        elif key == "audio_device":
            if not val:
                return False  # back to the automatic choice needs a restart
            mpvclient.mpv("set_property", "audio-device", val)
        else:
            return False
        _applied[key] = val
        return True
    except Exception:
        return False


def init_settings():
    _applied.update(current_values())


def sync_live():
    """Settings changed behind our back (HA's configuration page): apply the live ones."""
    cur = current_values()
    for k, spec in BY_KEY.items():
        if not spec["restart"] and _applied.get(k) != cur[k]:
            apply_live(k, cur[k])


def labels(lang):
    """Names and descriptions of the options from translations/<lang>.yaml (fallback English)."""
    out = {}
    for code in ("en", lang):
        try:
            import yaml

            d = yaml.safe_load(open(os.path.join(config.TRANSLATIONS, f"{code}.yaml")))["configuration"]
            for k, v in d.items():
                out[k] = {"name": v.get("name", k), "description": v.get("description", "")}
        except Exception:
            pass
    return out


def settings_view(lang="en"):
    sync_live()
    ports = display.hdmi_ports()
    modes = display.drm_modes()
    sizes = {(m["w"], m["h"]) for lst in modes.values() for m in lst if not m["interlaced"]}
    hz = sorted({str(round(m["hz"])) for lst in modes.values() for m in lst if m["hz"] and not m["interlaced"]})
    devs = [d.get("name", "") for d in (mpvclient.prop("audio-device-list") or [])]
    items = []
    for spec in SETTINGS:
        it = dict(spec)
        k = spec["key"]
        if k == "hdmi_port":
            it["unavailable"] = [c for c in spec["choices"] if c != "auto" and c not in [p["name"] for p in ports]]
        elif k == "video_mode":
            it["unavailable"] = [
                c for c in spec["choices"] if c in display.VIDEO_PRESETS and display.VIDEO_PRESETS[c] not in sizes
            ]
        elif k == "video_refresh":
            it["unavailable"] = [c for c in spec["choices"] if c != "auto" and hz and c not in hz]
        elif k == "cec" and cec.cec_state["state"] in cec.CEC_LOCKED:
            it["locked"] = cec.cec_state["state"]  # the web UI greys the option out and says why
        elif k == "audio_device":
            it["suggestions"] = [d for d in devs if d.split("/")[0] in ("pulse", "alsa") and "hdmi" in d.lower()]
        items.append(it)
    cur = current_values()
    return {
        "items": items,
        "values": cur,
        "labels": labels(lang),
        "pending_restart": pending_restart(cur),
        "can_save": supervisor.available(),
        "defaults": DEFAULTS,
        "version": config.app_version(),
    }


def validate_setting(key, val):
    spec = BY_KEY.get(key)
    if not spec:
        raise ValueError(f"setting '{key}' cannot be changed here")
    t = spec["type"]
    if t == "bool":
        if not isinstance(val, bool):
            raise ValueError(f"{key}: true or false expected")
    elif t == "int":
        if isinstance(val, bool) or not isinstance(val, int) or not spec["min"] <= val <= spec["max"]:
            raise ValueError(f"{key}: integer {spec['min']}..{spec['max']} expected")
    elif t == "choice":
        if val not in spec["choices"]:
            raise ValueError(f"{key}: one of {spec['choices']} expected")
    elif t == "str":
        if not isinstance(val, str) or len(val) > 200 or re.search(r"[\x00-\x1f]", val):
            raise ValueError(f"{key}: text expected")
    return val


OBSOLETE_OPTIONS = ("subtitles", "listen", "api_port", "api_token")


def save_settings(values):
    """Validate, store as the app's options through the Supervisor, apply what can be applied now."""
    for k, v in values.items():
        validate_setting(k, v)
    if not supervisor.available():
        raise RuntimeError("saving needs the Supervisor API (hassio_api); not available here")
    merged = {**read_options(), **values}  # keeps the options not shown in the web UI
    for k in OBSOLETE_OPTIONS:  # options of older versions the schema no longer has
        merged.pop(k, None)
    try:
        supervisor.post("/addons/self/options", {"options": merged})
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("message", str(e))
        except Exception:
            msg = str(e)
        raise RuntimeError(f"Supervisor rejected the options: {msg}") from e
    _saved.update(values)
    live = [k for k, v in values.items() if apply_live(k, v)]
    mpvclient.changed()
    return {"ok": True, "applied_now": live, "pending_restart": pending_restart(current_values())}

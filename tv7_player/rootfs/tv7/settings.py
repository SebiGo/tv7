"""Settings: editable in the web UI and the TV menu, stored as the app's options by the Supervisor."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from tv7 import cec, config, display, mpvclient, supervisor


def _c(*v):
    return list(v)


# key, type (choice | bool), choices, default, restart (needs an app restart), nerd (technical: the web UI and the TV
# menu show it only in nerd mode or when it differs from the default). config.yaml has the same options and defaults
# (tests/test_files.py checks that).
SETTINGS = [
    {
        "key": "hdmi_port",
        "type": "choice",
        "choices": _c("auto", "HDMI-A-1", "HDMI-A-2"),
        "default": "auto",
        "restart": True,
        "nerd": False,
    },
    {"key": "cec", "type": "choice", "choices": _c("auto", "off"), "default": "auto", "restart": True, "nerd": False},
    {
        "key": "video_mode",
        "type": "choice",
        "choices": _c("auto", "highest", "2160p", "1080p", "720p"),
        "default": "auto",
        "restart": True,
        "nerd": True,
    },
    {
        "key": "decode_speed",
        "type": "choice",
        "choices": _c("quality", "fast"),
        "default": "quality",
        "restart": True,
        "nerd": True,
    },
    {
        "key": "audio_channels",
        "type": "choice",
        "choices": _c("auto", "stereo"),
        "default": "auto",
        "restart": False,
        "nerd": False,
    },
    {
        "key": "idle_stop",
        "type": "choice",
        "choices": _c("off", "60", "120", "180", "240", "480"),
        "default": "off",
        "restart": False,
        "nerd": False,
    },
    {"key": "debug", "type": "bool", "default": False, "restart": True, "nerd": True},
]
BY_KEY = {x["key"]: x for x in SETTINGS}
DEFAULTS = {x["key"]: x["default"] for x in SETTINGS}
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
        if key == "audio_channels":
            mpvclient.mpv("set_property", "audio-channels", "stereo" if val == "stereo" else "auto-safe")
        elif key == "idle_stop":
            pass  # read by the watcher on every check
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
        except Exception as e:
            config.log_once("Option names (translations)", e)
    return out


def settings_view(lang="en"):
    sync_live()
    ports = display.hdmi_ports()
    modes = display.drm_modes()
    sizes = {(m["w"], m["h"]) for lst in modes.values() for m in lst if not m["interlaced"]}
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
        elif k == "cec" and cec.cec_state["state"] in cec.CEC_LOCKED:
            it["locked"] = cec.cec_state["state"]  # the web UI greys the option out and says why
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
    elif val not in spec["choices"]:
        raise ValueError(f"{key}: one of {spec['choices']} expected")
    return val


# options the schema does not have, which a saved options file may still contain: saving drops them, because the
# Supervisor refuses unknown options
OBSOLETE_OPTIONS = (
    "subtitles", "listen", "api_port", "api_token", "hdmi_disconnect", "video_output", "video_refresh", "deinterlace",
    "hardware_decoding", "audio_output", "audio_device", "audio_language", "start_volume",
)  # fmt: skip


def save_settings(values):
    """Validate, store as the app's options through the Supervisor, apply what can be applied now."""
    for k, v in values.items():
        validate_setting(k, v)
    if not supervisor.available():
        raise RuntimeError("saving needs the Supervisor API (hassio_api); not available here")
    merged = {**read_options(), **values}  # keeps the options not shown in the web UI
    for k in OBSOLETE_OPTIONS:
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

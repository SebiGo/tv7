"""Configuration of the app: version, paths, addresses and times, web UI access, texts (i18n), log lines.

Everything that tests and the development server (dev/run-web.sh) change is read here, once, from TV7_* environment
variables; the other modules use these values through config.<NAME>. In production none of them is set."""

import glob
import ipaddress
import json
import os
import time


def _env(name, default, kind=str):
    v = os.environ.get(name)
    return default if v is None else kind(v)


# the folder with control.py, ui.html, i18n/, translations/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = _env("TV7_VERSION", "")  # app version (build argument of the image)
STARTED = time.time()

# --- Web UI (Home Assistant Ingress) ---
UI_PORT = _env("TV7_UI_PORT", 0, int)  # 0 = no web UI (control.py sets 8099 in production)
UI_BIND = _env("TV7_UI_BIND", "172.30.32.1")  # the app's address on the Supervisor's network (Ingress connects here)
# who may connect: the Supervisor's address; networks for development
UI_ALLOW = [
    ipaddress.ip_network(x.strip(), strict=False) for x in _env("TV7_UI_ALLOW", "172.30.32.2").split(",") if x.strip()
]
UI_FILE = _env("TV7_UI_FILE", os.path.join(ROOT, "ui.html"))
UI_LOGO = os.path.join(ROOT, "ui-logo.png")
DEV_RELOAD = _env("TV7_DEV_RELOAD", "") == "1"  # development only (dev/run-web.sh): live reload of the web UI
EVENTS_S = _env("TV7_EVENTS_S", 3.0, float)  # /events sends the status at least this often (live values)

# --- Home Assistant: Supervisor, options, data ---
SUPERVISOR = _env("TV7_SUPERVISOR", "http://supervisor")
SUPERVISOR_TOKEN = _env("SUPERVISOR_TOKEN", "")  # set by the Supervisor (hassio_api)
OPTIONS_FILE = _env("TV7_OPTIONS", "/data/options.json")
TRANSLATIONS = _env("TV7_TRANSLATIONS", os.path.join(ROOT, "translations"))
FAV_FILE = _env("TV7_FAVORITES", "/data/favorites.json")  # favorite channels (ids), shared by all users of the web UI
LOGO_DIR = _env("TV7_LOGO_DIR", "/data/logos")  # cache of channel logos

# --- Init7 ---
INIT7_API = _env("TV7_API", "https://api.tv.init7.net/api/tvchannel/")  # public Init7 channel list
SRG_FHD = _env("TV7_SRG_FHD", "true") == "true"  # SRG Full HD list (H.265); off only in tests
SRG_MC_URL = _env("TV7_SRG_MC_URL", "https://www.init7.net/files/srg-fhd-mc.m3u")
SRG_HLS_URL = _env("TV7_SRG_HLS_URL", "https://www.init7.net/files/srg-fhd-hls.m3u")
# only logos from these addresses (tests serve their own)
LOGO_PREFIXES = tuple(
    _env("TV7_LOGO_PREFIX", "https://api.tv.init7.net/media/logos/,https://vtvapi03.sys.init7.net/media/logos/").split(
        ","
    )
)

# --- Devices and programs ---
DRM_DIR = _env("TV7_DRM_DIR", "/sys/class/drm")  # HDMI connectors in sysfs
MODETEST = _env("TV7_MODETEST", "modetest")  # lists the display's modes and the DRM planes
CEC_CTL = _env("TV7_CEC_CTL", "cec-ctl")
CEC_GLOB = _env("TV7_CEC_GLOB", "/dev/cec*")
OSD_CACHE = _env("TV7_OSD_CACHE", "/tmp/tv7-osd")  # logos converted for mpv's overlay-add
# the video output when mpv was started by someone else (tests, dev/run-web.sh): e.g. "vo=drm pending=yes hw=no mode=preferred"
VIDEO_START = dict(x.split("=", 1) for x in _env("TV7_VIDEO", "").split() if "=" in x)
HW_AVAILABLE = _env("TV7_HW_AVAILABLE", "no")  # the same for "H.265 is decoded in hardware"

# --- Times (seconds) ---
START_TIMEOUT = _env("TV7_START_TIMEOUT", 10.0, float)  # a channel attempt that does not play by then has failed
MODE_WAIT_S = _env("TV7_MODE_WAIT_S", 25.0, float)  # wait this long for mpv to come back after a restart
HDMI_OFF_S = _env("TV7_HDMI_OFF_S", 15.0, float)  # display gone this long: stop playback
HDMI_BACK_S = _env("TV7_HDMI_BACK_S", 3.0, float)  # display back this long: resume
HDMI_POLL_S = _env("TV7_HDMI_POLL_S", 2.0, float)  # how often the watcher checks
MINUTE_S = _env("TV7_MINUTE_S", 60.0, float)  # length of a minute for idle_stop (tests shorten it)
CEC_AWAY_S = _env("TV7_CEC_AWAY_S", 30.0, float)  # the TV shows another source this long: stop
CEC_CORE_WAIT_S = _env("TV7_CEC_CORE_WAIT_S", 300.0, float)  # wait this long for Home Assistant Core to finish starting
CEC_CORE_POLL_S = _env("TV7_CEC_CORE_POLL_S", 10.0, float)
MENU_TIMEOUT_S = _env("TV7_MENU_TIMEOUT_S", 12.0, float)  # the TV menu closes without a key
DIGIT_S = _env("TV7_DIGIT_S", 1.6, float)  # pause after the last digit before the channel number is taken

# --- Texts ---
# Texts of the web UI ("ui") and of the TV menu, banner and technical info ("tv") in English, German, French and Italian: one file
# per language. The option names and descriptions are in translations/<lang>.yaml (Home Assistant's format for the configuration page).
I18N_DIR = os.path.join(ROOT, "i18n")
I18N = {lg: json.load(open(os.path.join(I18N_DIR, f"{lg}.json"), encoding="utf-8")) for lg in ("en", "de", "fr", "it")}
TV_LABELS = {lg: d["tv"] for lg, d in I18N.items()}
UI_TEXTS = json.dumps({lg: d["ui"] for lg, d in I18N.items()}, ensure_ascii=False).encode()


def app_version():
    """The app version. The web UI reloads itself when it changes; with TV7_DEV_RELOAD the modification time of the UI files,
    the texts and the program is appended, so the open page reloads after every edit (live reload during development)."""
    if not DEV_RELOAD:
        return VERSION
    stamp = 0
    for f in (
        UI_FILE,
        UI_LOGO,
        os.path.join(ROOT, "control.py"),
        *glob.glob(os.path.join(ROOT, "tv7", "*.py")),
        *glob.glob(os.path.join(TRANSLATIONS, "*.yaml")),
        *glob.glob(os.path.join(ROOT, "i18n", "*.json")),
    ):
        try:
            stamp = max(stamp, os.stat(f).st_mtime_ns)
        except OSError:
            pass
    return f"{VERSION}+{stamp}"


def ui_client_ok(addr):
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
    except ValueError:
        return False
    return any(ip in n for n in UI_ALLOW if n.version == ip.version)


def log_line(msg):
    print(">>> " + msg, flush=True)  # goes to the app log

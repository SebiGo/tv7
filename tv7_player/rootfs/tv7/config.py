"""Configuration of the app: version, paths, web UI and Supervisor access, texts (i18n), log lines."""
import glob
import ipaddress
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the folder with control.py, ui.html, i18n/, translations/


UI_PORT = int(os.environ.get("TV7_UI_PORT", "0"))                       # 0 = no web UI
UI_BIND = os.environ.get("TV7_UI_BIND", "172.30.32.1")                  # the app's address on the Supervisor's network (Ingress connects here)
UI_ALLOW = [ipaddress.ip_network(x.strip(), strict=False) for x in os.environ.get("TV7_UI_ALLOW", "172.30.32.2").split(",") if x.strip()]  # the Supervisor's address (Ingress); networks allowed (for development)


def app_version():
    """The app version. The web UI reloads itself when it changes; with TV7_DEV_RELOAD the modification time of the UI files,
    the texts and the program is appended, so the open page reloads after every edit (live reload during development)."""
    if not DEV_RELOAD:
        return VERSION
    stamp = 0
    for f in (UI_FILE, UI_LOGO, os.path.join(ROOT, "control.py"), *glob.glob(os.path.join(ROOT, "tv7", "*.py")),
              *glob.glob(os.path.join(TRANSLATIONS, "*.yaml")), *glob.glob(os.path.join(ROOT, "i18n", "*.json"))):
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


UI_LOGO = os.environ.get("TV7_UI_LOGO", os.path.join(ROOT, "ui-logo.png"))
UI_FILE = os.environ.get("TV7_UI_FILE", os.path.join(ROOT, "ui.html"))
OPTIONS_FILE = os.environ.get("TV7_OPTIONS", "/data/options.json")
SUPERVISOR = os.environ.get("TV7_SUPERVISOR", "http://supervisor")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
TRANSLATIONS = os.environ.get("TV7_TRANSLATIONS", os.path.join(ROOT, "translations"))
VERSION = os.environ.get("TV7_VERSION", "")                              # app version (build argument of the image)
DEV_RELOAD = os.environ.get("TV7_DEV_RELOAD") == "1"                     # development only (dev/run-web.sh): live reload of the web UI
STARTED = time.time()
# Texts of the web UI ("ui") and of the TV menu, banner and technical info ("tv") in English, German, French and Italian: one file
# per language. The option names and descriptions are in translations/<lang>.yaml (Home Assistant's format for the configuration page).
I18N_DIR = os.environ.get("TV7_I18N", os.path.join(ROOT, "i18n"))
I18N = {lg: json.load(open(os.path.join(I18N_DIR, f"{lg}.json"), encoding="utf-8")) for lg in ("en", "de", "fr", "it")}
TV_LABELS = {lg: d["tv"] for lg, d in I18N.items()}
UI_TEXTS = json.dumps({lg: d["ui"] for lg, d in I18N.items()}, ensure_ascii=False).encode()


def log_line(msg):
    print(">>> " + msg, flush=True)                               # goes to the app log

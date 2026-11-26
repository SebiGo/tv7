"""Home Assistant's Supervisor API: the app's options and restart, its log, the system versions, and Core's /api/config.
All calls need the token the Supervisor gives the app (hassio_api); without it (development, tests without it) they are off."""

import json
import re
import threading
import time
import urllib.request

from tv7 import config


def available():
    return bool(config.SUPERVISOR_TOKEN)


def _request(path, data=None, headers=None, method=None):
    h = {"Authorization": f"Bearer {config.SUPERVISOR_TOKEN}", **(headers or {})}
    return urllib.request.Request(config.SUPERVISOR + path, data=data, headers=h, method=method)


def post(path, payload=None):
    """POST JSON (options, restart); raises urllib.error.HTTPError when the Supervisor refuses."""
    req = _request(path, json.dumps(payload or {}).encode(), {"Content-Type": "application/json"}, "POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def get_json(path, timeout=10):
    """GET JSON; None if the Supervisor is not available or does not answer."""
    if not available():
        return None
    try:
        with urllib.request.urlopen(_request(path), timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def core_config():
    """Home Assistant Core's /api/config (state, loaded integrations, language); None if not reachable."""
    return get_json("/core/api/config")


def info():
    """Versions of Home Assistant OS, Core and Supervisor plus machine type (empty outside Home Assistant)."""
    d = (get_json("/info", timeout=5) or {}).get("data", {})
    return (
        {k: d.get(k) for k in ("hassos", "homeassistant", "supervisor", "machine", "arch", "operating_system")}
        if d
        else {}
    )


def app_log(lines):
    """The last lines of this app's own log, without colour codes."""
    if not available():
        return []
    try:
        req = _request("/addons/self/logs", headers={"Accept": "text/plain", "Range": f"entries=:-{lines}:"})
        with urllib.request.urlopen(req, timeout=8) as r:
            text = r.read(400000).decode("utf-8", "replace")
        return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text).splitlines()[-lines:]
    except Exception:
        return []


def restart_app(delay=0.5):
    """Ask the Supervisor to restart the app, after delay (so the answer to the request that asked for it still goes out)."""
    threading.Thread(target=lambda: (time.sleep(delay), post("/addons/self/restart")), daemon=True).start()

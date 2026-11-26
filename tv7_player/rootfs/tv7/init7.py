"""Init7 channel lists (TV7 and SRG Full HD), stream addresses (Init7 only), channel logos, favorites."""

import hashlib
import ipaddress
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from tv7 import config

# only HLS URLs from Init7
HLS_PREFIXES = ("https://api.tv.init7.net/", "https://vtvapi03.sys.init7.net/")
CACHE_S = 300  # the channel lists are fetched again after this
UDP_OPTS = "fifo_size=65536&overrun_nonfatal=1"  # FFmpeg UDP input options for multicast
_cache = {"t": 0.0, "data": [], "srg": []}
# channel list sync state (support text)
_sync = {
    "tv7_ok": None,
    "tv7_error": None,
    "srg_ok": None,
    "srg_error": None,
    "tried": None,
}


def sync_info():
    """The channel lists for the support text: channel counts (srg None when the list is off) and the last sync."""
    srg = len(_cache["srg"]) if config.SRG_FHD else None
    return {"tv7": sum(1 for c in _cache["data"] if c.get("list") == "tv7"), "srg": srg, **_sync}


def logo_file(url):
    """Channel logo (PNG/JPEG) from Init7: only URLs under config.LOGO_PREFIXES, cached on disk. Returns (bytes, content
    type)."""
    if (
        not url.startswith(config.LOGO_PREFIXES)
        or not re.search(r"\.(png|jpe?g)$", url, re.I)
        or re.search(r"[\s\x00-\x1f]", url)
    ):
        raise PermissionError("not an Init7 logo URL")
    ctype = "image/png" if url.lower().endswith(".png") else "image/jpeg"
    path = os.path.join(config.LOGO_DIR, hashlib.sha256(url.encode()).hexdigest())
    try:
        return open(path, "rb").read(), ctype
    except OSError:
        pass
    with urllib.request.urlopen(url, timeout=10) as r:
        data = r.read(400001)
    if len(data) > 400000 or not data:
        raise ValueError("logo too large or empty")
    try:
        os.makedirs(config.LOGO_DIR, exist_ok=True)
        open(path, "wb").write(data)
    except OSError:
        pass
    return data, ctype


def load_favorites():
    try:
        d = json.load(open(config.FAV_FILE))
        return [x for x in d if isinstance(x, str)][:200] if isinstance(d, list) else []
    except Exception:
        return []


def save_favorites(ids):
    if not isinstance(ids, list) or len(ids) > 200 or not all(isinstance(x, str) and 0 < len(x) <= 200 for x in ids):
        raise ValueError("favorites: a list of up to 200 channel ids expected")
    ids = list(dict.fromkeys(ids))
    tmp = config.FAV_FILE + ".tmp"
    os.makedirs(os.path.dirname(config.FAV_FILE) or ".", exist_ok=True)
    with open(tmp, "w") as f:
        json.dump(ids, f)
    os.replace(tmp, config.FAV_FILE)
    return ids


def parse_m3u(text):
    """Parse an Init7 .m3u playlist: [{"name", "nr", "group", "url"}]."""
    out, cur = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF"):
            nr = re.search(r'tvg-chno="(\d+)"', line)
            grp = re.search(r'group-title="([^"]*)"', line)
            logo = re.search(r'tvg-logo="([^"]*)"', line)
            cur = {
                "name": line.rsplit(",", 1)[-1].strip(),
                "nr": int(nr.group(1)) if nr else None,
                "group": grp.group(1) if grp else "",
                "logo": logo.group(1) if logo else None,
            }
        elif line and not line.startswith("#") and cur:
            out.append({**cur, "url": line})
            cur = None
    return out


def srg_fhd_channels():
    """The SRG Full HD list (separate multicast and HLS playlists on init7.net), merged by channel name."""

    def get(url):
        with urllib.request.urlopen(url, timeout=10) as r:
            return parse_m3u(r.read().decode("utf-8", "replace"))

    mc = {c["name"]: c for c in get(config.SRG_MC_URL)}
    hls = {c["name"]: c for c in get(config.SRG_HLS_URL)}
    out = []
    for name in sorted(set(mc) | set(hls), key=lambda n: (mc.get(n) or hls.get(n))["nr"] or 1e9):
        c = mc.get(name) or hls.get(name)
        out.append(
            {
                "pk": "srg-fhd:" + name,
                "name": name,
                "ordernum": c["nr"],
                "hd": True,
                "visible": True,
                "list": "srg_fhd",
                "logo": c.get("logo"),
                "src": mc[name]["url"] if name in mc else None,
                "has_hls": name in hls,
                "hls_src": hls[name]["url"] if name in hls else None,
            }
        )
    return out


_refresh_lock = threading.Lock()  # one load at a time


def _refresh():
    """Load the channel lists from Init7 (TV7, plus SRG Full HD). On a network error the last loaded lists stay; without
    any list it raises."""
    _sync["tried"] = time.time()
    try:
        out, url = [], config.INIT7_API
        while url:
            with urllib.request.urlopen(url, timeout=10) as r:
                d = json.load(r)
            out += d["results"]
            url = d.get("next")
        tv7 = [{**c, "list": "tv7"} for c in out if c.get("visible", True)]
        srg = _cache["srg"]
        if config.SRG_FHD:
            try:
                srg = srg_fhd_channels()
                _sync.update(srg_ok=time.time(), srg_error=None)
            except Exception as e:
                _sync["srg_error"] = str(e)  # keep the last SRG list; TV7 must not depend on it
        else:
            srg = []
        _cache.update(t=time.time(), data=tv7 + srg, srg=srg)
        _sync.update(tv7_ok=time.time(), tv7_error=None)
    except Exception as e:
        _sync["tv7_error"] = str(e)
        if not _cache["data"]:
            raise RuntimeError(f"Init7 channel list not reachable: {e}") from e


def _refresh_in_background():
    def run():
        try:
            _refresh()
        except Exception:
            pass  # recorded in _sync (support text); the next call tries again
        finally:
            _refresh_lock.release()

    if _refresh_lock.acquire(blocking=False):  # a load is running already otherwise
        threading.Thread(target=run, daemon=True).start()


def channels(force=False, block=True):
    """The channel lists. A list older than CACHE_S is returned at once and loaded again in the background, so a key
    press or a page never waits for Init7. Only the first load and force (the web UI's "reload list") wait.
    block=False never waits: before the first load it returns [] and starts loading (TV menu, which holds its lock)."""
    if force or (block and not _cache["data"]):
        with _refresh_lock:
            if force or not _cache["data"]:
                _refresh()
    elif not _cache["data"] or time.time() - _cache["t"] > CACHE_S:
        _refresh_in_background()
    return _cache["data"]


def find_channel(sel, block=True):
    """Find a channel by pk, number or name (exact match, otherwise a unique partial match). block: see channels()."""
    sel = sel.strip()
    low = sel.lower()
    chs = channels(block=block)
    for c in chs:
        if sel == c["pk"] or low == c["name"].lower() or sel == str(c.get("ordernum")):
            return c
    hits = [c for c in chs if low in c["name"].lower()]
    if len(hits) == 1:
        return hits[0]
    raise KeyError(f"Channel '{sel}' not found" + (f" (ambiguous: {[h['name'] for h in hits][:5]})" if hits else ""))


def multicast_url(src):
    """udp://@233.x.x.x:port -> ffmpeg notation; real multicast addresses only. The receive buffer (fifo_size, in
    188-byte packets, about 12 MB) bridges a few seconds in which the player does not read; overrun_nonfatal drops
    packets instead of ending the stream when it still overflows (a short picture glitch instead of a stop)."""
    m = re.fullmatch(r"udp://@?(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})", src or "")
    if not m or not ipaddress.ip_address(m[1]).is_multicast:
        return None
    return f"udp://{m[1]}:{m[2]}?{UDP_OPTS}"


def stream_url(ch, source):
    if source == "multicast":
        u = multicast_url(ch.get("src"))
        if u:
            return u
    if ch.get("has_hls") and str(ch.get("hls_src", "")).startswith(HLS_PREFIXES):
        return ch["hls_src"]
    raise KeyError("no suitable stream source")

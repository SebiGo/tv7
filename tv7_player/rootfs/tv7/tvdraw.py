"""Drawing on the TV with mpv's OSD: an ASS overlay in 1920x1080 coordinates (mpv scales it to the output) for panels, text
and selections, and overlay-add images for the logos. Also the language of the TV texts and the logo cache."""

import hashlib
import os
import threading
import time

from tv7 import config, init7, mpvclient, png, supervisor


def ass_escape(s):
    return str(s).replace("\\", "/").replace("{", "(").replace("}", ")")


OSD_CACHE = os.environ.get("TV7_OSD_CACHE", "/tmp/tv7-osd")  # logos converted for overlay-add
FONT = "Inter"  # fontconfig falls back to DejaVu Sans if missing
ACCENT, WHITE = "&H7468ED&", "&HFFFFFF&"  # TV7 coral (237, 104, 116), white (ASS colours are BGR)
ACCENT_A, ACCENT_B = "&H7C70F0&", "&H5C4AE0&"  # the web UI's accent gradient #f0707c -> #e04a5c
PANEL_A, PANEL_B = "&H312823&", "&H26202C&"  # the web UI's dark card gradient #232831 -> #2c2026
_ovl = {}  # overlay-add slot -> parameters currently shown
_logo_bgra = {}  # logo URL (or "brand") -> (path, w, h) | False (unusable) | "pending"
_logo_sem = threading.Semaphore(2)
# called when a logo is ready; control.py adds the TV menu's redraw
on_logo_ready = []
_lang = {}  # ha: Home Assistant's language, asked: the language /osd?lang= asked for


def lang():
    """Language of the TV texts: Home Assistant's, else the one /osd asked for, else English."""
    return _lang.get("ha") or _lang.get("asked") or "en"


def set_asked_lang(code):
    _lang["asked"] = code


def ha_language_loop():
    """Language of the TV menu: Home Assistant's language (the TV has no browser that could tell)."""
    for _ in range(40):
        cfg = supervisor.core_config()
        code = str((cfg or {}).get("language") or "")[:2].lower()
        if code:
            _lang["ha"] = code if code in config.TV_LABELS else "en"
            return
        if not supervisor.available():
            return
        time.sleep(15)


def labels():
    return config.TV_LABELS.get(lang(), config.TV_LABELS["en"])


def alpha(a, f):
    """ASS alpha (0 = opaque, 255 = invisible) of an element with transparency a, faded in to the fraction f."""
    return f"&H{max(0, min(255, round(255 - (255 - a) * f))):02X}&"


def rounded_rect(x, y, w, h, r):
    """ASS drawing of a rounded rectangle."""
    k = round(r * 0.45)
    x, y, w, h, r = (round(v) for v in (x, y, w, h, r))
    return (
        f"m {x + r} {y} l {x + w - r} {y} b {x + w - k} {y} {x + w} {y + k} {x + w} {y + r} l {x + w} {y + h - r} "
        f"b {x + w} {y + h - k} {x + w - k} {y + h} {x + w - r} {y + h} l {x + r} {y + h} b {x + k} {y + h} {x} {y + h - k} {x} {y + h - r} "
        f"l {x} {y + r} b {x} {y + k} {x + k} {y} {x + r} {y}"
    )


def text(x, y, txt, size, a, f, an=4, bold=False, color=WHITE, extra=""):
    return rf"{{\an{an}\pos({round(x)},{round(y)})\fn{FONT}\fs{size}\b{1 if bold else 0}\bord0\shad0\1c{color}\1a{alpha(a, f)}{extra}}}{ass_escape(txt)}"


def clip(txt, n):
    return txt if len(txt) <= n else txt[: n - 1] + "…"


def shape(path, color, a, extra=""):
    return rf"{{\an7\pos(0,0)\bord0\shad0\1c{color}\1a&H{a:02X}&{extra}\p1}}{path}"


def panel_bg(x, y, w, h, r):
    """Panel like the web UI's dark cards: diagonal gradient, a coral glow in the top right corner, translucent, with a soft
    shadow and a faint light edge. Drawn as its own overlay (rendered once when it appears)."""
    box = rounded_rect(x, y, w, h, r)
    clip_box = rf"\clip({box})"
    return [
        shape(rounded_rect(x, y + 14, w, h, r), "&H000000&", 0x70, r"\blur30"),
        shape(box, PANEL_A, 0x30),
        shape(
            f"m {x + w} {y} l {x + w} {y + h} l {x} {y + h}", PANEL_B, 0x30, r"\blur90" + clip_box
        ),  # gradient towards the bottom right
        shape(rounded_rect(x + w - 300, y - 260, 520, 520, 260), ACCENT, 0xC0, r"\blur110" + clip_box),  # coral glow
        shape(box, WHITE, 0xFF, r"\bord1.5\3c&HFFFFFF&\3a&HD8&"),
    ]


def pill(x, y, w, h, r, glow=True):
    """Selection in the accent gradient (left lighter), with a soft glow."""
    box = rounded_rect(x, y, w, h, r)
    out = [shape(box, ACCENT, 0xA8, r"\blur14")] if glow else []
    return out + [
        shape(box, ACCENT_B, 0x18),
        shape(rounded_rect(x - 40, y - 20, w * 0.6, h + 40, 0), ACCENT_A, 0x18, r"\blur40" + rf"\clip({box})"),
    ]


def logo_bgra(url):
    """Logo converted for overlay-add, or None while it is being converted / if it cannot be used (JPEG, unusual PNG)."""
    if not url:
        return None
    v = _logo_bgra.get(url)
    if v is None:
        _logo_bgra[url] = "pending"
        threading.Thread(target=_convert_logo, args=(url,), daemon=True).start()
        return None
    return v if isinstance(v, tuple) else None


def _convert_logo(url):
    with _logo_sem:
        try:
            if url == "brand":
                data = open(config.UI_LOGO, "rb").read()
            else:
                data, ctype = init7.logo_file(url)
                if ctype != "image/png":
                    raise ValueError("not a PNG")
            w, h, px = png.png_bytes_to_bgra(data)
            os.makedirs(OSD_CACHE, exist_ok=True)
            path = os.path.join(OSD_CACHE, hashlib.sha256(url.encode()).hexdigest() + ".bgra")
            with open(path, "wb") as fh:
                fh.write(px)
            _logo_bgra[url] = (path, w, h)
        except Exception:
            _logo_bgra[url] = False
    for fn in on_logo_ready:  # the menu or banner shows it now if it is still up
        try:
            fn()
        except Exception:
            pass


def place_logos(slots, placements):
    """Show logos (url, x, y, w, h in 1920x1080 coordinates, fitted into that box) in the given overlay-add slots; clear the rest."""
    ow, oh = mpvclient.prop("osd-width"), mpvclient.prop("osd-height")
    want = {}
    if ow and oh:
        sx, sy = ow / 1920, oh / 1080
        for slot, (url, x, y, w, h) in zip(slots, placements, strict=False):
            lg = logo_bgra(url)
            if not lg:
                continue
            path, iw, ih = lg
            sc = min(w / iw, h / ih)
            dw, dh = iw * sc, ih * sc
            want[slot] = (
                round((x + (w - dw) / 2) * sx),
                round((y + (h - dh) / 2) * sy),
                path,
                iw,
                ih,
                max(1, round(dw * sx)),
                max(1, round(dh * sy)),
            )
    for slot in slots:
        if slot in want and _ovl.get(slot) != want[slot]:
            x, y, path, iw, ih, dw, dh = want[slot]
            mpvclient.mpv_keep(["overlay-add", slot, x, y, path, 0, "bgra", iw, ih, iw * 4, dw, dh])
            _ovl[slot] = want[slot]
        elif slot not in want and slot in _ovl:
            mpvclient.mpv_keep(["overlay-remove", slot])
            del _ovl[slot]

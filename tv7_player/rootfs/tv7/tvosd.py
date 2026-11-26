"""On the TV: the technical info, the menu, the channel banner and the remote control keys (drawn with mpv's OSD)."""

import hashlib
import os
import socket
import threading
import time

from tv7 import cec, config, display, init7, mpvclient, player, settings, system

OSD_S = float(os.environ.get("TV7_OSD_S", "1"))  # refresh interval of the overlay
OSD_ID = 7  # overlay id (osd-overlay); the idle logo uses overlay-add, separate
osd_state = {"on": False, "lang": None, "shown": False, "rows": None}


def _num(v):
    """A finite number from an mpv property, else None."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def osd_lines(lang="en"):
    """The technical info of the player's nerd mode as lines of text (label, value)."""
    L = config.TV_LABELS.get(lang, config.TV_LABELS["en"])
    p = {
        k: mpvclient.prop(k)
        for k in (
            "video-codec",
            "video-params",
            "container-fps",
            "estimated-vf-fps",
            "video-bitrate",
            "audio-codec-name",
            "audio-params",
            "osd-width",
            "osd-height",
            "display-fps",
            "current-vo",
            "hwdec-current",
            "frame-drop-count",
            "decoder-frame-drop-count",
        )
    }
    for k in ("container-fps", "estimated-vf-fps", "video-bitrate", "display-fps"):
        p[k] = _num(p[k])  # mpv reports an unknown rate as the text "nan"
    vp, ap, sysl = p["video-params"] or {}, p["audio-params"] or {}, system.system_load()
    fps = p["container-fps"] or p["estimated-vf-fps"]

    def join(*xs):
        return " · ".join(str(x) for x in xs if x)

    def res(w, h):
        return f"{w}×{h}" if w and h else None

    stream = join(
        res(vp.get("w"), vp.get("h")) and res(vp.get("w"), vp.get("h")) + (f" @ {fps:.0f} fps" if fps else ""),
        p["video-codec"] and p["video-codec"].split()[0],
        p["video-bitrate"] and f"{p['video-bitrate'] / 1e6:.1f} Mbit/s",
    )
    ch = ap.get("hr-channels") or ap.get("channels")
    audio = join(p["audio-codec-name"], ch, ap.get("samplerate") and f"{ap['samplerate'] / 1000:g} kHz")
    hw = p["hwdec-current"] and p["hwdec-current"] != "no"
    output = join(
        res(p["osd-width"], p["osd-height"])
        and res(p["osd-width"], p["osd-height"]) + (f" @ {p['display-fps']:.0f} Hz" if p["display-fps"] else ""),
        p["current-vo"] and f"{L['render']} {'GPU' if str(p['current-vo']).startswith('gpu') else 'CPU'}",
    )
    decode = (L["hw"] if hw else L["sw"]) + (f" ({p['hwdec-current']})" if hw else "")
    frames = join(
        p["frame-drop-count"] is not None and f"{p['frame-drop-count']} {L['dropped']}",
        p["decoder-frame-drop-count"] is not None and f"{L['decoder']} {p['decoder-frame-drop-count']}",
    )
    sysline = join(
        sysl.get("total") is not None and f"CPU {sysl['total']:.0f}%",
        sysl.get("mpv") is not None and f"mpv {sysl['mpv']:.0f}%",
        sysl.get("temp_c") is not None and f"{sysl['temp_c']:.0f} °C",
    )
    head = join(player.current["name"], player.current["source"])
    return [(None, head)] + [
        (L[k], v)
        for k, v in (
            ("stream", stream),
            ("audio", audio),
            ("output", output),
            ("decode", decode),
            ("frames", frames),
            ("system", sysline),
        )
        if v
    ]


def _ass(text):
    return str(text).replace("\\", "/").replace("{", "(").replace("}", ")")


OSD_BG_ID = 12  # osd-overlay id of the box behind the technical info
TX, TY, TW = 1920 - 64 - 680, 64, 680  # technical info: top right, next to the menu (left) and banner (bottom)
T_HEAD, T_ROW = 70, 40


def osd_box_height(n_rows):
    return T_HEAD + n_rows * T_ROW + 22


def osd_ass(lines):
    """ASS text of the technical info box: channel as title with an accent bar, then label (grey) and value (white) per row."""
    head = next((v for lab, v in lines if lab is None), "")
    rows = [(lab, v) for lab, v in lines if lab is not None]
    out = [
        _draw(_rr(TX + 24, TY + 22, 6, 34, 3), ACCENT, 0x00),
        _text(TX + 44, TY + 40, _clip(head, 34), 28, 0x00, 1, bold=True),
    ]
    for i, (lab, val) in enumerate(rows):
        y = TY + T_HEAD + i * T_ROW + T_ROW / 2
        out.append(_text(TX + 44, y, lab, 21, 0x68, 1))
        out.append(_text(TX + 196, y, _clip(val, 42), 22, 0x08, 1))
    return "\n".join(out)


def osd_step():
    """Show or refresh the technical info while it is on and a channel plays; remove it otherwise. The box behind it is its own
    overlay and is drawn again only when the number of rows changes."""
    want = osd_state["on"] and mpvclient.playing()
    if want:
        lines = osd_lines(osd_state["lang"] or menu_lang())
        n = len([x for x in lines if x[0] is not None])
        if osd_state.get("rows") != n or not osd_state["shown"]:
            mpvclient.mpv_named(
                name="osd-overlay",
                id=OSD_BG_ID,
                format="ass-events",
                data="\n".join(_panel_bg(TX, TY, TW, osd_box_height(n), 26)),
                res_x=1920,
                res_y=1080,
                z=6,
            )
            osd_state["rows"] = n
        mpvclient.mpv_named(
            name="osd-overlay", id=OSD_ID, format="ass-events", data=osd_ass(lines), res_x=1920, res_y=1080, z=7
        )
        osd_state["shown"] = True
    elif osd_state["shown"]:
        _osd_hide_tech()


def osd_loop():
    last_err = {}
    while True:
        for step in (osd_step, menu_tick):
            try:
                step()
                last_err.pop(step.__name__, None)
            except Exception as e:
                if last_err.get(step.__name__) != str(e):  # log each new error once, not every second
                    last_err[step.__name__] = str(e)
                    if not isinstance(e, (ConnectionError, FileNotFoundError, socket.timeout)):
                        config.log_line(f"TV overlay ({step.__name__}): {type(e).__name__}: {e}")
        time.sleep(OSD_S)


# Drawn with mpv's OSD: an ASS overlay in 1920x1080 coordinates (scaled by mpv to the output) for the translucent panels, text and
# selection, and overlay-add images for the logos (they are drawn above the ASS layer). Menu: OK opens it; up/down move, left/right
# switch tabs (channels, audio, subtitles, more), OK selects, back closes; it closes by itself after MENU_TIMEOUT_S. Without the
# menu: channel up/down zap, digits choose a channel number, info toggles the technical info. Every channel start shows a banner.
# osd-overlay ids (the technical info uses OSD_ID). The background of a
MENU_ID, BANNER_ID, MENU_BG_ID, BANNER_BG_ID = (
    8,
    9,
    10,
    11,
)
# overlay-add slots: brand logo, banner logo, row logos 20..31 (idle logo: 0)
OVL_BRAND, OVL_BANNER, OVL_ROWS = (
    19,
    32,
    20,
)
MENU_TIMEOUT_S = float(os.environ.get("TV7_MENU_TIMEOUT_S", "12"))
BANNER_S = float(os.environ.get("TV7_BANNER_S", "4"))
DIGIT_S = float(os.environ.get("TV7_DIGIT_S", "1.6"))  # pause after the last digit before the channel number is taken
OSD_CACHE = os.environ.get("TV7_OSD_CACHE", "/tmp/tv7-osd")  # logos converted for overlay-add
MENU_ROWS, ROW_H = 10, 66
FONT = "Inter"  # fontconfig falls back to DejaVu Sans if missing
ACCENT, WHITE = "&H7468ED&", "&HFFFFFF&"  # TV7 coral (237, 104, 116), white (ASS colours are BGR)
ACCENT_A, ACCENT_B = "&H7C70F0&", "&H5C4AE0&"  # the web UI's accent gradient #f0707c -> #e04a5c
PANEL_A, PANEL_B = "&H312823&", "&H26202C&"  # the web UI's dark card gradient #232831 -> #2c2026
TABS = ("channels", "audio", "subs", "settings")
VOLUME_STEPS = (50, 60, 70, 80, 90, 100, 110, 120, 130)
LANG_NAMES = {
    "deu": "Deutsch",
    "ger": "Deutsch",
    "fra": "Français",
    "fre": "Français",
    "ita": "Italiano",
    "eng": "English",
    "roh": "Rumantsch",
    "spa": "Español",
    "por": "Português",
    "tur": "Türkçe",
}
menu = {
    "open": False,
    "tab": 0,
    "sel": [0, 0, 0, 0],
    "top": [0, 0, 0, 0],
    "t": 0.0,
    "nerd": False,
    "msg": None,
    "msg_t": 0.0,
}
banner = {"shown": False, "until": 0.0, "ch": None, "status": None, "digits": None}
digits = {"buf": "", "timer": None}
_ovl = {}  # overlay-add slot -> parameters currently shown
_logo_bgra = {}  # logo URL (or "brand") -> (path, w, h) | False (unusable) | "pending"
_logo_sem = threading.Semaphore(2)
_menu_lock = threading.RLock()
_ha_lang = {}


def menu_lang():
    return _ha_lang.get("lang") or osd_state.get("lang") or "en"


def ha_language_loop():
    """Language of the TV menu: Home Assistant's language (the TV has no browser that could tell)."""
    for _ in range(40):
        cfg = cec.ha_core_config()
        lang = str((cfg or {}).get("language") or "")[:2].lower()
        if lang:
            _ha_lang["lang"] = lang if lang in config.TV_LABELS else "en"
            return
        if not config.SUPERVISOR_TOKEN:
            return
        time.sleep(15)


def ML():
    return config.TV_LABELS.get(menu_lang(), config.TV_LABELS["en"])


def _al(a, f):
    """ASS alpha (0 = opaque, 255 = invisible) of an element with transparency a, faded in to the fraction f."""
    return f"&H{max(0, min(255, round(255 - (255 - a) * f))):02X}&"


def _rr(x, y, w, h, r):
    """ASS drawing of a rounded rectangle."""
    k = round(r * 0.45)
    x, y, w, h, r = (round(v) for v in (x, y, w, h, r))
    return (
        f"m {x + r} {y} l {x + w - r} {y} b {x + w - k} {y} {x + w} {y + k} {x + w} {y + r} l {x + w} {y + h - r} "
        f"b {x + w} {y + h - k} {x + w - k} {y + h} {x + w - r} {y + h} l {x + r} {y + h} b {x + k} {y + h} {x} {y + h - k} {x} {y + h - r} "
        f"l {x} {y + r} b {x} {y + k} {x + k} {y} {x + r} {y}"
    )


def _text(x, y, txt, size, alpha, f, an=4, bold=False, color=WHITE, extra=""):
    return rf"{{\an{an}\pos({round(x)},{round(y)})\fn{FONT}\fs{size}\b{1 if bold else 0}\bord0\shad0\1c{color}\1a{_al(alpha, f)}{extra}}}{_ass(txt)}"


def _clip(txt, n):
    return txt if len(txt) <= n else txt[: n - 1] + "…"


def _draw(path, color, alpha, extra=""):
    return rf"{{\an7\pos(0,0)\bord0\shad0\1c{color}\1a&H{alpha:02X}&{extra}\p1}}{path}"


def _panel_bg(x, y, w, h, r):
    """Panel like the web UI's dark cards: diagonal gradient, a coral glow in the top right corner, translucent, with a soft
    shadow and a faint light edge. Drawn as its own overlay (rendered once when it appears)."""
    box = _rr(x, y, w, h, r)
    clip = rf"\clip({box})"
    return [
        _draw(_rr(x, y + 14, w, h, r), "&H000000&", 0x70, r"\blur30"),
        _draw(box, PANEL_A, 0x30),
        _draw(
            f"m {x + w} {y} l {x + w} {y + h} l {x} {y + h}", PANEL_B, 0x30, r"\blur90" + clip
        ),  # gradient towards the bottom right
        _draw(_rr(x + w - 300, y - 260, 520, 520, 260), ACCENT, 0xC0, r"\blur110" + clip),  # coral glow
        _draw(box, WHITE, 0xFF, r"\bord1.5\3c&HFFFFFF&\3a&HD8&"),
    ]


def _pill(x, y, w, h, r, glow=True):
    """Selection in the accent gradient (left lighter), with a soft glow."""
    box = _rr(x, y, w, h, r)
    out = [_draw(box, ACCENT, 0xA8, r"\blur14")] if glow else []
    return out + [
        _draw(box, ACCENT_B, 0x18),
        _draw(_rr(x - 40, y - 20, w * 0.6, h + 40, 0), ACCENT_A, 0x18, r"\blur40" + rf"\clip({box})"),
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
            w, h, px = display.png_bytes_to_bgra(data)
            os.makedirs(OSD_CACHE, exist_ok=True)
            path = os.path.join(OSD_CACHE, hashlib.sha256(url.encode()).hexdigest() + ".bgra")
            with open(path, "wb") as fh:
                fh.write(px)
            _logo_bgra[url] = (path, w, h)
        except Exception:
            _logo_bgra[url] = False
    try:
        with _menu_lock:  # show it now if the menu or banner is still up
            if menu["open"]:
                render_menu()
            if banner["shown"]:
                render_banner()
    except Exception:
        pass


def _place(slots, placements):
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


def menu_items(tab):
    """Entries of a tab: {"kind": "header"|"item", "label", "right", "logo", "mark" (current/selected), "act": (action, arg)}."""
    L = ML()
    if TABS[tab] == "channels":
        try:
            chs = init7.channels()
        except Exception:
            chs = []
        by, out = {c["pk"]: c for c in chs}, []

        def add(title, lst):
            if lst:
                out.append({"kind": "header", "label": title})
                out.extend(
                    {
                        "kind": "item",
                        "label": c["name"],
                        "right": str(c.get("ordernum") or "") if menu["nerd"] else "",
                        "logo": c.get("logo"),
                        "mark": c["pk"] == player.current["pk"],
                        "act": ("play", c["pk"]),
                    }
                    for c in lst
                )

        add(L["favorites"], [by[p] for p in init7.load_favorites() if p in by])
        add("SRG Full HD", [c for c in chs if c.get("list") == "srg_fhd"])
        add("TV7", [c for c in chs if c.get("list", "tv7") == "tv7"])
        return out or [{"kind": "header", "label": L["none"]}]
    if TABS[tab] in ("audio", "subs"):
        audio = TABS[tab] == "audio"
        tr = mpvclient.tracks()["audio" if audio else "sub"]
        out = (
            []
            if audio
            else [{"kind": "item", "label": L["off"], "mark": not any(t["selected"] for t in tr), "act": ("sid", "no")}]
        )
        for t in tr:
            name = LANG_NAMES.get(t.get("lang") or "", (t.get("lang") or "").upper() or f"#{t['id']}")
            out.append(
                {
                    "kind": "item",
                    "label": " – ".join(x for x in (name, t.get("title")) if x),
                    "right": " ".join(x for x in (t.get("codec"), t.get("channels") and f"{t['channels']}ch") if x),
                    "mark": t["selected"],
                    "act": ("aid" if audio else "sid", t["id"]),
                }
            )
        return out or [{"kind": "header", "label": L["none"]}]
    vals, names, pend = settings.current_values(), settings.labels(menu_lang()), settings.pending_restart()
    out = []
    for group in ("video", "audio", "system"):  # the groups of the web UI's settings
        out.append({"kind": "header", "label": L["g_" + group]})
        for spec in settings.SETTINGS:
            k = spec["key"]
            if spec["group"] != group or spec["type"] == "str":  # free text (audio_device): only in the web UI
                continue
            if spec["nerd"] and not menu["nerd"] and str(vals.get(k)) == str(settings.DEFAULTS.get(k)):
                continue  # technical: only in nerd mode, or when changed (like the web UI)
            locked = k == "cec" and cec.cec_state["state"] in cec.CEC_LOCKED
            out.append(
                {
                    "kind": "item",
                    "label": names.get(k, {}).get("name", k),
                    "right": _setting_label(spec, vals.get(k)) + (f" · {L['restart_tag']}" if k in pend else ""),
                    "act": None if locked else ("set", k),
                }
            )
    if pend and config.SUPERVISOR_TOKEN:
        out.append({"kind": "item", "label": L["restart"], "mark": True, "act": ("restart", None)})
    out.append({"kind": "item", "label": L["stop"], "act": ("stop", None)})
    out += [
        {"kind": "header", "label": L["g_display"]},
        {
            "kind": "item",
            "label": L["tech"],
            "right": L["on"] if osd_state["on"] else L["off"],
            "mark": osd_state["on"],
            "act": ("tech", None),
        },
        {
            "kind": "item",
            "label": L["nerd"],
            "right": L["on"] if menu["nerd"] else L["off"],
            "mark": menu["nerd"],
            "act": ("nerd", None),
        },
    ]
    return out


def _selectable(items):
    return [i for i, it in enumerate(items) if it["kind"] == "item"]


MX, MY, MW, MH = 64, 64, 720, 952  # menu panel
LIST_Y = MY + 200


def render_menu_bg():
    out = _panel_bg(MX, MY, MW, MH, 30)
    out.append(_draw(_rr(MX + 32, MY + 182, MW - 64, 2, 1), WHITE, 0xE0))
    mpvclient.mpv_named(
        name="osd-overlay", id=MENU_BG_ID, format="ass-events", data="\n".join(out), res_x=1920, res_y=1080, z=5
    )


def render_menu(sel_y=None, logos=True):
    tab = menu["tab"]
    items = menu_items(tab)
    sel, top = menu["sel"][tab], menu["top"][tab]
    L = ML()
    out = [_text(MX + MW - 40, MY + 50, time.strftime("%H:%M"), 32, 0x30, 1, an=6)]
    x = MX + 30
    for i, name in enumerate(TABS):  # tabs: the active one as a pill in the accent gradient
        label = L[name]
        w = len(label) * 14 + 36
        if i == tab:
            out += _pill(x, MY + 106, w, 50, 25, glow=False)
        out.append(_text(x + w / 2, MY + 131, label, 25, 0x00 if i == tab else 0x70, 1, an=5, bold=i == tab))
        x += w + 8
    vis = items[top : top + MENU_ROWS]
    chan = TABS[tab] == "channels"
    if sel_y is None:
        sel_y = LIST_Y + (sel - top) * ROW_H
    if items and items[min(sel, len(items) - 1)]["kind"] == "item":
        out += _pill(MX + 18, sel_y + 4, MW - 36, ROW_H - 8, 20)
    places = []
    for i, it in enumerate(vis):
        y = LIST_Y + i * ROW_H
        if it["kind"] == "header":
            out.append(
                _text(MX + 44, y + ROW_H - 14, it["label"].upper(), 20, 0x78, 1, an=1, bold=True, extra=r"\fsp3")
            )
            continue
        is_sel = top + i == sel
        dim = it.get("act") is None  # shown, but cannot be changed here
        if it.get("mark"):
            out.append(_draw(_rr(MX + 30, y + 21, 6, ROW_H - 42, 3), WHITE if is_sel else ACCENT, 0x00))
        tx = MX + 150 if chan else MX + 52
        out.append(
            _text(
                tx,
                y + ROW_H / 2,
                _clip(it["label"], 24 if chan else 30),
                30 if chan else 27,
                0x70 if dim else 0x00 if is_sel else 0x18,
                1,
                bold=is_sel,
            )
        )
        if it.get("right"):
            out.append(
                _text(MX + MW - 44, y + ROW_H / 2, _clip(it["right"], 18), 22, 0x40 if is_sel else 0x80, 1, an=6)
            )
        if chan:
            places.append((it.get("logo"), MX + 50, y + 11, 84, ROW_H - 22))
    if top > 0:
        out.append(_text(MX + MW / 2, LIST_Y - 6, "▲", 18, 0x90, 1, an=5))
    if top + MENU_ROWS < len(items):
        out.append(_text(MX + MW / 2, LIST_Y + MENU_ROWS * ROW_H + 8, "▼", 18, 0x90, 1, an=5))
    msg = menu["msg"] if menu["msg"] and time.time() - menu["msg_t"] < 4 else None
    out.append(_text(MX + MW / 2, MY + MH - 40, msg or L["hint"], 21, 0x20 if msg else 0x90, 1, an=5, bold=bool(msg)))
    mpvclient.mpv_named(
        name="osd-overlay", id=MENU_ID, format="ass-events", data="\n".join(out), res_x=1920, res_y=1080, z=10
    )
    _place([OVL_BRAND], [("brand", MX + 36, MY + 26, 96, 50)] if logos else [])
    _place(list(range(OVL_ROWS, OVL_ROWS + MENU_ROWS)), places if logos else [])


BX, BW, BH = 480, 960, 156  # channel banner, bottom centre
BY = 1080 - 72 - BH


def render_banner(logos=True):
    L = ML()
    out = []
    ch, st = banner["ch"], banner["status"]
    if banner["digits"] is not None:
        out.append(_text(BX + 48, BY + BH / 2 - 26, L["channel"], 24, 0x60, 1))
        out.append(_text(BX + 48, BY + BH / 2 + 22, banner["digits"] + "_", 56, 0x00, 1, bold=True, extra=r"\fsp4"))
        places = []
    else:
        name = ch["name"] if ch else ""
        number = str(ch.get("ordernum") or "") if ch and menu["nerd"] else ""  # channel numbers only in nerd mode
        sub = " · ".join(
            x
            for x in (
                number,
                player.current["source"] if st == "ok" and player.current["source"] else "",
                L["starting"]
                if st == "starting"
                else L["failed"]
                if st == "failed"
                else L["notfound"]
                if st == "notfound"
                else "",
            )
            if x
        )
        out.append(_draw(_rr(BX + 22, BY + 30, 6, BH - 60, 3), ACCENT, 0x00))
        out.append(_text(BX + 236, BY + 64, _clip(name, 30), 44, 0x00, 1, bold=True))
        out.append(
            _text(
                BX + 236,
                BY + 112,
                sub,
                26,
                0x50 if st != "failed" else 0x00,
                1,
                color=ACCENT if st == "failed" else WHITE,
            )
        )
        places = [(ch.get("logo"), BX + 50, BY + 28, 160, BH - 56)] if ch and logos else []
    mpvclient.mpv_named(
        name="osd-overlay", id=BANNER_ID, format="ass-events", data="\n".join(out), res_x=1920, res_y=1080, z=9
    )
    _place([OVL_BANNER], places)


def open_menu():
    tab = menu["tab"] = 0
    items = menu_items(tab)
    sel = next((i for i, it in enumerate(items) if it.get("mark")), None)
    if sel is None:
        sel = (_selectable(items) or [0])[0]
    menu["sel"][tab] = sel
    menu["top"][tab] = max(0, min(sel - MENU_ROWS // 2, len(items) - MENU_ROWS))
    menu.update(open=True, t=time.time(), msg=None)
    render_menu_bg()
    render_menu()


def close_menu():
    if not menu["open"]:
        return
    menu["open"] = False
    for i in (MENU_ID, MENU_BG_ID):
        mpvclient.mpv_named(name="osd-overlay", id=i, format="none", data="")
    _place([OVL_BRAND] + list(range(OVL_ROWS, OVL_ROWS + MENU_ROWS)), [])


def menu_move(d):
    tab = menu["tab"]
    items = menu_items(tab)
    sel_list = _selectable(items)
    if not sel_list:
        return
    old = menu["sel"][tab]
    pos = sel_list.index(old) if old in sel_list else 0
    new = sel_list[max(0, min(len(sel_list) - 1, pos + d))]
    top = menu["top"][tab]
    if new == sel_list[0]:
        top = 0  # first entry: show its header too
    elif new < top + 1:
        top = max(0, new - 1)
    elif new > top + MENU_ROWS - 2:
        top = min(new - MENU_ROWS + 2, max(0, len(items) - MENU_ROWS))
    scrolled = top != menu["top"][tab]
    menu["sel"][tab], menu["top"][tab] = new, top
    if scrolled or new == old:
        render_menu()
        return
    y0, y1 = LIST_Y + (old - top) * ROW_H, LIST_Y + (new - top) * ROW_H
    for i in (1, 2, 3):  # let the selection glide (only the small content overlay changes)
        render_menu(sel_y=y0 + (y1 - y0) * (1 - (1 - i / 3) ** 2))
        time.sleep(1 / 40)


def menu_tab(d):
    menu["tab"] = (menu["tab"] + d) % len(TABS)
    tab = menu["tab"]
    items = menu_items(tab)
    if TABS[tab] != "channels" or menu["sel"][tab] >= len(items) or items[menu["sel"][tab]]["kind"] != "item":
        marked = next((i for i, it in enumerate(items) if it.get("mark") and it["kind"] == "item"), None)
        menu["sel"][tab] = marked if marked is not None and TABS[tab] != "settings" else (_selectable(items) or [0])[0]
        menu["top"][tab] = max(0, min(menu["sel"][tab] - MENU_ROWS // 2, len(items) - MENU_ROWS))
    render_menu()


def _setting_next(spec, val):
    """The next value of a setting for OK in the TV menu (values the display does not offer are skipped)."""
    if spec["type"] == "bool":
        return not val
    if spec["type"] == "int":
        steps = list(VOLUME_STEPS)
        return next((v for v in steps if v > (val or 0)), steps[0])
    choices = spec["choices"]
    try:
        un = next(
            (
                x.get("unavailable") or []
                for x in settings.settings_view(menu_lang())["items"]
                if x["key"] == spec["key"]
            ),
            [],
        )
    except Exception:
        un = []
    ok = [c for c in choices if c not in un] or choices
    i = ok.index(val) if val in ok else -1
    return ok[(i + 1) % len(ok)]


def _setting_label(spec, val):
    L = ML()
    if spec["type"] == "bool":
        return L["on"] if val else L["off"]
    if spec["key"] == "idle_stop":
        return L["off"] if val == "off" else f"{val} min"
    return str(val)


def _keep_selection(tab, act, row):
    """After the list of a tab changed (nerd mode shows more settings, a restart entry appears): select the same entry again and
    keep it on the same row of the screen, so the menu does not jump."""
    items = menu_items(tab)
    idx = next((i for i, it in enumerate(items) if it.get("act") == act), None)
    if idx is None:
        return
    menu["sel"][tab] = idx
    menu["top"][tab] = max(0, min(idx - row, max(0, len(items) - MENU_ROWS)))


def menu_activate():
    tab = menu["tab"]
    items = menu_items(tab)
    if not items or menu["sel"][tab] >= len(items) or items[menu["sel"][tab]]["kind"] != "item":
        return
    act, arg = items[menu["sel"][tab]].get("act") or (None, None)
    row = menu["sel"][tab] - menu["top"][tab]
    L = ML()
    if act == "play":
        close_menu()
        play_async(init7.find_channel(arg))
    elif act in ("aid", "sid"):
        mpvclient.mpv("set_property", act, arg)
        render_menu()
    elif act == "tech":
        set_osd(not osd_state["on"], menu_lang())
        render_menu()
    elif act == "nerd":
        menu["nerd"] = not menu["nerd"]
        _keep_selection(tab, (act, arg), row)
        render_menu()
    elif act == "set":
        spec = settings.BY_KEY[arg]
        new = _setting_next(spec, settings.current_values().get(arg))
        try:
            settings.save_settings({arg: new})
            menu.update(
                msg=f"{L['saved']}: {settings.labels(menu_lang()).get(arg, {}).get('name', arg)} = {_setting_label(spec, new)}",
                msg_t=time.time(),
            )
        except Exception as e:
            menu.update(msg=f"{L['save_failed']}: {e}", msg_t=time.time())
            config.log_line(f"TV menu: {arg} not saved: {e}")
        _keep_selection(tab, (act, arg), row)  # a restart entry may have appeared
        render_menu()
    elif act == "restart":
        close_menu()
        threading.Thread(
            target=lambda: (time.sleep(0.5), settings.supervisor_call("/addons/self/restart")), daemon=True
        ).start()
    elif act == "stop":
        close_menu()
        player.stop_playback(wait=False)


def show_banner(ch=None, status=None, digits_text=None, seconds=None):
    first = not banner["shown"]
    banner.update(
        shown=True,
        ch=ch,
        status=status,
        digits=digits_text,
        until=time.time() + (seconds if seconds is not None else BANNER_S),
    )
    if first:
        mpvclient.mpv_named(
            name="osd-overlay",
            id=BANNER_BG_ID,
            format="ass-events",
            data="\n".join(_panel_bg(BX, BY, BW, BH, 30)),
            res_x=1920,
            res_y=1080,
            z=4,
        )
    render_banner()


def hide_banner():
    if not banner["shown"]:
        return
    banner["shown"] = False
    _place([OVL_BANNER], [])
    for i in (BANNER_ID, BANNER_BG_ID):
        mpvclient.mpv_named(name="osd-overlay", id=i, format="none", data="")


def play_async(ch, source="auto"):
    """Start a channel from the remote control without blocking the keys; the banner shows progress and result."""
    show_banner(ch, "starting", seconds=120)

    def run():
        t0 = time.time()
        player.hdmi_stopped.clear()
        player.autostopped.clear()
        try:
            res = player.start(ch, source)
        except Exception as e:
            res = {"ok": False, "log": [str(e)]}
        player.last_start.clear()
        player.last_start.update(t=t0, seconds=round(time.time() - t0, 1), requested=source, **res)
        with _menu_lock:
            if banner["ch"] is ch:
                show_banner(ch, "ok" if res["ok"] else "failed")

    player.player(run, wait=False)


def zap(d):
    try:
        chs = init7.channels()
    except Exception:
        return
    cur = next((c for c in chs if c["pk"] == player.current["pk"]), None)
    lst = cur.get("list", "tv7") if cur else "tv7"
    pool = [c for c in chs if c.get("list", "tv7") == lst]
    if not pool:
        return
    i = pool.index(cur) if cur in pool else (-1 if d > 0 else 0)
    play_async(pool[(i + d) % len(pool)])


def _digit(d):
    digits["buf"] = (digits["buf"] + d)[-4:]
    if digits["timer"]:
        digits["timer"].cancel()
    show_banner(digits_text=digits["buf"], seconds=DIGIT_S + 1)
    digits["timer"] = threading.Timer(DIGIT_S, _digit_commit)
    digits["timer"].daemon = True
    digits["timer"].start()


def _digit_commit():
    with _menu_lock:
        buf, digits["buf"], digits["timer"] = digits["buf"], "", None
        try:
            ch = next((c for c in init7.channels() if str(c.get("ordernum")) == buf), None)
        except Exception:
            ch = None
        if ch:
            play_async(ch)
        else:
            show_banner({"name": buf, "ordernum": None}, "notfound")


def _osd_hide_tech():
    if osd_state["shown"]:
        try:
            for i in (OSD_ID, OSD_BG_ID):
                mpvclient.mpv_named(name="osd-overlay", id=i, format="none", data="")
        except Exception:
            pass
        osd_state.update(shown=False, rows=None)


def handle_key(key):
    """One remote control key (CEC or /key)."""
    player.touch()
    with _menu_lock:
        if key.isdigit():
            if menu["open"]:
                close_menu()
            _digit(key)
            return
        if menu["open"]:
            menu["t"] = time.time()
            if key in ("up", "down"):
                menu_move(-1 if key == "up" else 1)
            elif key in ("left", "right"):
                menu_tab(-1 if key == "left" else 1)
            elif key == "ok":
                menu_activate()
            elif key in ("back", "info"):
                close_menu()
            elif key in ("ch_up", "ch_down"):
                close_menu()
                zap(1 if key == "ch_up" else -1)
            return
        if key == "ok":
            hide_banner()
            open_menu()
        elif key in ("ch_up", "ch_down"):
            zap(1 if key == "ch_up" else -1)
        elif key == "info":
            set_osd(not osd_state["on"], menu_lang())
        elif key == "stop":
            player.stop_playback(wait=False)
        elif key == "play" and not player.current["pk"] and player.last_played:
            try:
                play_async(init7.find_channel(player.last_played["pk"]), player.last_played.get("source") or "auto")
            except KeyError:
                pass
        elif key == "back":
            hide_banner()


def menu_tick():
    """Called about once a second: close the menu after MENU_TIMEOUT_S without a key, hide the banner when its time is up."""
    with _menu_lock:
        now = time.time()
        if menu["open"] and now - menu["t"] >= MENU_TIMEOUT_S:
            close_menu()
        if banner["shown"] and now >= banner["until"]:
            hide_banner()


def set_osd(on, lang=None):
    osd_state.update(on=bool(on), lang=lang if lang in config.TV_LABELS else None)  # None: Home Assistant's language
    mpvclient.changed()
    try:
        osd_step()
    except Exception:
        pass
    return {"on": osd_state["on"]}

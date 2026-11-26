"""The TV menu, the channel banner and the remote control keys (CEC or /key), drawn with tv7/tvdraw.py.

Menu: OK opens it; up/down move, left/right switch tabs (channels, audio, subtitles, settings), OK selects, back closes;
it closes by itself after config.MENU_TIMEOUT_S. Without the menu: channel up/down zap, digits choose a channel number,
info toggles the technical info. Every channel start shows a banner."""

import socket
import threading
import time

from tv7 import cec, config, init7, mpvclient, player, settings, supervisor, tvdraw, tvinfo

OSD_S = 1.0  # refresh interval of the overlay


def osd_loop():
    last_err = {}
    while True:
        for step in (tvinfo.osd_step, menu_tick):
            try:
                step()
                last_err.pop(step.__name__, None)
            except Exception as e:
                if last_err.get(step.__name__) != str(e):  # log each new error once, not every second
                    last_err[step.__name__] = str(e)
                    if not isinstance(e, (ConnectionError, FileNotFoundError, socket.timeout)):
                        config.log_line(f"TV overlay ({step.__name__}): {type(e).__name__}: {e}")
        time.sleep(OSD_S)


# osd-overlay ids (the technical info uses 7 and 12, see tv7/tvinfo.py)
MENU_ID, BANNER_ID, MENU_BG_ID, BANNER_BG_ID = 8, 9, 10, 11
# overlay-add slots: brand logo, banner logo, row logos 20..31 (idle logo: 0)
OVL_BRAND, OVL_BANNER, OVL_ROWS = 19, 32, 20
BANNER_S = 4.0
MENU_ROWS, ROW_H = 10, 66
TABS = ("channels", "audio", "subs", "settings")
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
_menu_lock = threading.RLock()


def menu_items(tab):
    """Entries of a tab: {"kind": "header"|"item", "label", "right", "logo", "mark" (current/selected), "act": (action,
    arg)}."""
    L = tvdraw.labels()
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
                        "mark": c["pk"] == player.state.current["pk"],
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
    vals, names, pend = settings.current_values(), settings.labels(tvdraw.lang()), settings.pending_restart()
    out = []
    for spec in settings.SETTINGS:
        k = spec["key"]
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
    if pend and supervisor.available():
        out.append({"kind": "item", "label": L["restart"], "mark": True, "act": ("restart", None)})
    out.append({"kind": "item", "label": L["stop"], "act": ("stop", None)})
    out += [
        {"kind": "header", "label": L["g_display"]},
        {
            "kind": "item",
            "label": L["tech"],
            "right": L["on"] if tvinfo.osd_state["on"] else L["off"],
            "mark": tvinfo.osd_state["on"],
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
    out = tvdraw.panel_bg(MX, MY, MW, MH, 30)
    out.append(tvdraw.shape(tvdraw.rounded_rect(MX + 32, MY + 182, MW - 64, 2, 1), tvdraw.WHITE, 0xE0))
    mpvclient.mpv_named(
        name="osd-overlay", id=MENU_BG_ID, format="ass-events", data="\n".join(out), res_x=1920, res_y=1080, z=5
    )


def render_menu(sel_y=None, logos=True):
    tab = menu["tab"]
    items = menu_items(tab)
    sel, top = menu["sel"][tab], menu["top"][tab]
    L = tvdraw.labels()
    out = [tvdraw.text(MX + MW - 40, MY + 50, time.strftime("%H:%M"), 32, 0x30, 1, an=6)]
    x = MX + 30
    for i, name in enumerate(TABS):  # tabs: the active one as a pill in the accent gradient
        label = L[name]
        w = len(label) * 14 + 36
        if i == tab:
            out += tvdraw.pill(x, MY + 106, w, 50, 25, glow=False)
        out.append(tvdraw.text(x + w / 2, MY + 131, label, 25, 0x00 if i == tab else 0x70, 1, an=5, bold=i == tab))
        x += w + 8
    vis = items[top : top + MENU_ROWS]
    chan = TABS[tab] == "channels"
    if sel_y is None:
        sel_y = LIST_Y + (sel - top) * ROW_H
    if items and items[min(sel, len(items) - 1)]["kind"] == "item":
        out += tvdraw.pill(MX + 18, sel_y + 4, MW - 36, ROW_H - 8, 20)
    places = []
    for i, it in enumerate(vis):
        y = LIST_Y + i * ROW_H
        if it["kind"] == "header":
            out.append(
                tvdraw.text(MX + 44, y + ROW_H - 14, it["label"].upper(), 20, 0x78, 1, an=1, bold=True, extra=r"\fsp3")
            )
            continue
        is_sel = top + i == sel
        dim = it.get("act") is None  # shown, but cannot be changed here
        if it.get("mark"):
            out.append(
                tvdraw.shape(
                    tvdraw.rounded_rect(MX + 30, y + 21, 6, ROW_H - 42, 3),
                    tvdraw.WHITE if is_sel else tvdraw.ACCENT,
                    0x00,
                )
            )
        tx = MX + 150 if chan else MX + 52
        out.append(
            tvdraw.text(
                tx,
                y + ROW_H / 2,
                tvdraw.clip(it["label"], 24 if chan else 30),
                30 if chan else 27,
                0x70 if dim else 0x00 if is_sel else 0x18,
                1,
                bold=is_sel,
            )
        )
        if it.get("right"):
            out.append(
                tvdraw.text(
                    MX + MW - 44, y + ROW_H / 2, tvdraw.clip(it["right"], 18), 22, 0x40 if is_sel else 0x80, 1, an=6
                )
            )
        if chan:
            places.append((it.get("logo"), MX + 50, y + 11, 84, ROW_H - 22))
    if top > 0:
        out.append(tvdraw.text(MX + MW / 2, LIST_Y - 6, "▲", 18, 0x90, 1, an=5))
    if top + MENU_ROWS < len(items):
        out.append(tvdraw.text(MX + MW / 2, LIST_Y + MENU_ROWS * ROW_H + 8, "▼", 18, 0x90, 1, an=5))
    msg = menu["msg"] if menu["msg"] and time.time() - menu["msg_t"] < 4 else None
    out.append(
        tvdraw.text(MX + MW / 2, MY + MH - 40, msg or L["hint"], 21, 0x20 if msg else 0x90, 1, an=5, bold=bool(msg))
    )
    mpvclient.mpv_named(
        name="osd-overlay", id=MENU_ID, format="ass-events", data="\n".join(out), res_x=1920, res_y=1080, z=10
    )
    tvdraw.place_logos([OVL_BRAND], [("brand", MX + 36, MY + 26, 96, 50)] if logos else [])
    tvdraw.place_logos(list(range(OVL_ROWS, OVL_ROWS + MENU_ROWS)), places if logos else [])


BX, BW, BH = 480, 960, 156  # channel banner, bottom centre
BY = 1080 - 72 - BH


def render_banner(logos=True):
    L = tvdraw.labels()
    out = []
    ch, st = banner["ch"], banner["status"]
    if banner["digits"] is not None:
        out.append(tvdraw.text(BX + 48, BY + BH / 2 - 26, L["channel"], 24, 0x60, 1))
        out.append(
            tvdraw.text(BX + 48, BY + BH / 2 + 22, banner["digits"] + "_", 56, 0x00, 1, bold=True, extra=r"\fsp4")
        )
        places = []
    else:
        name = ch["name"] if ch else ""
        number = str(ch.get("ordernum") or "") if ch and menu["nerd"] else ""  # channel numbers only in nerd mode
        sub = " · ".join(
            x
            for x in (
                number,
                player.state.current["source"] if st == "ok" and player.state.current["source"] else "",
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
        out.append(tvdraw.shape(tvdraw.rounded_rect(BX + 22, BY + 30, 6, BH - 60, 3), tvdraw.ACCENT, 0x00))
        out.append(tvdraw.text(BX + 236, BY + 64, tvdraw.clip(name, 30), 44, 0x00, 1, bold=True))
        out.append(
            tvdraw.text(
                BX + 236,
                BY + 112,
                sub,
                26,
                0x50 if st != "failed" else 0x00,
                1,
                color=tvdraw.ACCENT if st == "failed" else tvdraw.WHITE,
            )
        )
        places = [(ch.get("logo"), BX + 50, BY + 28, 160, BH - 56)] if ch and logos else []
    mpvclient.mpv_named(
        name="osd-overlay", id=BANNER_ID, format="ass-events", data="\n".join(out), res_x=1920, res_y=1080, z=9
    )
    tvdraw.place_logos([OVL_BANNER], places)


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
    tvdraw.place_logos([OVL_BRAND] + list(range(OVL_ROWS, OVL_ROWS + MENU_ROWS)), [])


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
    choices = spec["choices"]
    try:
        un = next(
            (
                x.get("unavailable") or []
                for x in settings.settings_view(tvdraw.lang())["items"]
                if x["key"] == spec["key"]
            ),
            [],
        )
    except Exception:
        un = []
    ok = [c for c in choices if c not in un] or choices
    i = ok.index(val) if val in ok else -1
    return ok[(i + 1) % len(ok)]


def _setting_name(key):
    return settings.labels(tvdraw.lang()).get(key, {}).get("name", key)


def _setting_label(spec, val):
    L = tvdraw.labels()
    if spec["type"] == "bool":
        return L["on"] if val else L["off"]
    if spec["key"] == "idle_stop":
        return L["off"] if val == "off" else f"{val} min"
    return str(val)


def _keep_selection(tab, act, row):
    """After the list of a tab changed (nerd mode shows more settings, a restart entry appears): select the same entry
    again and keep it on the same row of the screen, so the menu does not jump."""
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
    L = tvdraw.labels()
    if act == "play":
        close_menu()
        play_async(init7.find_channel(arg))
    elif act in ("aid", "sid"):
        mpvclient.mpv("set_property", act, arg)
        render_menu()
    elif act == "tech":
        tvinfo.set_osd(not tvinfo.osd_state["on"], tvdraw.lang())
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
                msg=f"{L['saved']}: {_setting_name(arg)} = {_setting_label(spec, new)}",
                msg_t=time.time(),
            )
        except Exception as e:
            menu.update(msg=f"{L['save_failed']}: {e}", msg_t=time.time())
            config.log_line(f"TV menu: {arg} not saved: {e}")
        _keep_selection(tab, (act, arg), row)  # a restart entry may have appeared
        render_menu()
    elif act == "restart":
        close_menu()
        supervisor.restart_app()
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
            data="\n".join(tvdraw.panel_bg(BX, BY, BW, BH, 30)),
            res_x=1920,
            res_y=1080,
            z=4,
        )
    render_banner()


def hide_banner():
    if not banner["shown"]:
        return
    banner["shown"] = False
    tvdraw.place_logos([OVL_BANNER], [])
    for i in (BANNER_ID, BANNER_BG_ID):
        mpvclient.mpv_named(name="osd-overlay", id=i, format="none", data="")


def play_async(ch, source="auto"):
    """Start a channel from the remote control without blocking the keys; the banner shows progress and result."""
    show_banner(ch, "starting", seconds=120)

    def run():
        res = player.play(ch, source)
        with _menu_lock:
            if banner["ch"] is ch:
                show_banner(ch, "ok" if res["ok"] else "failed")

    player.player(run, wait=False)


def logo_ready():
    """A logo finished converting (tvdraw.on_logo_ready): draw the menu or banner again if it is up."""
    with _menu_lock:
        if menu["open"]:
            render_menu()
        if banner["shown"]:
            render_banner()


def resume(ch, source):
    """Start a channel again after the TV showed another source (player.handlers["resume"]), with the channel banner."""
    with _menu_lock:
        play_async(ch, source)


def zap(d):
    try:
        chs = init7.channels()
    except Exception:
        return
    cur = next((c for c in chs if c["pk"] == player.state.current["pk"]), None)
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
    show_banner(digits_text=digits["buf"], seconds=config.DIGIT_S + 1)
    digits["timer"] = threading.Timer(config.DIGIT_S, _digit_commit)
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
            tvinfo.set_osd(not tvinfo.osd_state["on"], tvdraw.lang())
        elif key == "stop":
            player.stop_playback(wait=False)
        elif key == "play" and not player.state.current["pk"] and player.state.last_played:
            try:
                play_async(
                    init7.find_channel(player.state.last_played["pk"]), player.state.last_played.get("source") or "auto"
                )
            except KeyError:
                pass
        elif key == "back":
            hide_banner()


def menu_tick():
    """Called about once a second: close the menu after config.MENU_TIMEOUT_S without a key, hide the banner when its
    time is up."""
    with _menu_lock:
        now = time.time()
        if menu["open"] and now - menu["t"] >= config.MENU_TIMEOUT_S:
            close_menu()
        if banner["shown"] and now >= banner["until"]:
            hide_banner()

"""The technical info on the TV picture (/osd, the info key): channel, stream, sound, output, decoding, frames, load."""

from tv7 import config, mpvclient, player, system, tvdraw

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
    head = join(player.state.current["name"], player.state.current["source"])
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
        tvdraw.shape(tvdraw.rounded_rect(TX + 24, TY + 22, 6, 34, 3), tvdraw.ACCENT, 0x00),
        tvdraw.text(TX + 44, TY + 40, tvdraw.clip(head, 34), 28, 0x00, 1, bold=True),
    ]
    for i, (lab, val) in enumerate(rows):
        y = TY + T_HEAD + i * T_ROW + T_ROW / 2
        out.append(tvdraw.text(TX + 44, y, lab, 21, 0x68, 1))
        out.append(tvdraw.text(TX + 196, y, tvdraw.clip(val, 42), 22, 0x08, 1))
    return "\n".join(out)


def osd_step():
    """Show or refresh the technical info while it is on and a channel plays; remove it otherwise. The box behind it is its own
    overlay and is drawn again only when the number of rows changes."""
    want = osd_state["on"] and mpvclient.playing()
    if want:
        lines = osd_lines(osd_state["lang"] or tvdraw.lang())
        n = len([x for x in lines if x[0] is not None])
        if osd_state.get("rows") != n or not osd_state["shown"]:
            mpvclient.mpv_named(
                name="osd-overlay",
                id=OSD_BG_ID,
                format="ass-events",
                data="\n".join(tvdraw.panel_bg(TX, TY, TW, osd_box_height(n), 26)),
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
        hide()


def playback_ended():
    """mpv went idle (mpvclient.on_idle): the technical info goes at once instead of at its next refresh."""
    if osd_state["shown"]:
        osd_step()


def hide():
    if osd_state["shown"]:
        try:
            for i in (OSD_ID, OSD_BG_ID):
                mpvclient.mpv_named(name="osd-overlay", id=i, format="none", data="")
        except Exception:
            pass
        osd_state.update(shown=False, rows=None)


def set_osd(on, lang=None):
    lang = lang if lang in config.TV_LABELS else None  # None: Home Assistant's language
    osd_state.update(on=bool(on), lang=lang)
    tvdraw.set_asked_lang(lang)
    mpvclient.changed()
    try:
        osd_step()
    except Exception:
        pass
    return {"on": osd_state["on"]}

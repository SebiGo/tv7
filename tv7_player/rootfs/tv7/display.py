"""The display: HDMI connectors, output modes, planes, deinterlacing and the video output state."""

import glob
import os
import re
import subprocess

from tv7 import config, hwdec, mpvclient


def connectors():
    try:
        return [os.path.join(config.DRM_DIR, d) for d in sorted(os.listdir(config.DRM_DIR)) if "-HDMI-A-" in d]
    except FileNotFoundError:
        return []


def hdmi_status():
    out = {}
    for c in connectors():
        try:
            out[os.path.basename(c)] = open(os.path.join(c, "status")).read().strip()
        except Exception as e:
            out[os.path.basename(c)] = f"?({e})"
    return out


def hdmi_ok():
    return "connected" in hdmi_status().values()


def update_deinterlace():
    """Deinterlace where the current decoder allows it (see deinterlace_possible). "auto" deinterlaces only frames that
    are interlaced (1080i channels), not the progressive ones (720p50, 1080p); mpv without "auto" gets "yes"."""
    try:
        if not hwdec.deinterlace_possible(mpvclient.prop("hwdec-current")):
            mpvclient.mpv("set_property", "deinterlace", False)
        elif mpvclient.mpv("set_property", "deinterlace", "auto").get("error") != "success":
            mpvclient.mpv("set_property", "deinterlace", True)
    except Exception as e:
        config.log_once("Deinterlacing", e)


def hdmi_ports():
    """HDMI connectors from sysfs: name, status, enabled and the first distinct modes."""
    out = []
    for c in connectors():

        def read(f, c=c):
            try:
                return open(os.path.join(c, f)).read().split()
            except Exception:
                return []

        name = os.path.basename(c).split("-", 1)[1]  # card1-HDMI-A-1 -> HDMI-A-1
        modes, allm = [], read("modes")
        for m in allm:
            if m not in modes:
                modes.append(m)
        out.append(
            {
                "all_modes": allm,
                "name": name,
                "card": os.path.basename(c).split("-", 1)[0],
                "status": (read("status") or ["?"])[0],
                "enabled": (read("enabled") or ["?"])[0],
                "modes": modes[:6],
            }
        )
    return out


def parse_modetest(text):
    """Parse `modetest -c`: {connector name: [{"index", "w", "h", "hz", "interlaced", "preferred"}]}."""
    res, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^\d+\s+\d+\s+(?:connected|disconnected|unknown)\s+(\S+)", line)
        if m:
            cur = res.setdefault(m.group(1), [])
            continue
        m = re.match(r"^\s+#(\d+)\s+(\d+)x(\d+)(i?)\s+([\d.]+)\s", line)
        if m and cur is not None:
            cur.append(
                {
                    "index": int(m.group(1)),
                    "w": int(m.group(2)),
                    "h": int(m.group(3)),
                    "interlaced": bool(m.group(4)),
                    "hz": float(m.group(5)),
                    "preferred": "preferred" in line,
                }
            )
    return res


def parse_planes(text):
    """`modetest -p`: the planes that show a picture (framebuffer set) with type, alpha, blend mode, zpos, colour
    encoding/range."""
    return [{k: v for k, v in pl.items() if k != "blend_enums"} for pl in parse_planes_all(text) if pl["fb"]]


def parse_planes_all(text):
    """All planes of `modetest -p` (with or without a picture), with their properties and the enum values of the blend
    mode."""
    planes, cur, prop_name, enums = [], None, None, {}
    for line in text.splitlines():
        m = re.match(r"^(\d+)\s+(\d+)\s+(\d+)\s+\d+,\d+\s+\d+,\d+", line)
        if m:
            cur = {"id": int(m[1]), "crtc": int(m[2]), "fb": int(m[3]), "blend_enums": {}}
            planes.append(cur)
            continue
        if cur is None:
            continue
        pm = re.match(r"^\s+\d+ ([A-Za-z_ ]+):\s*$", line)
        if pm:
            prop_name, enums = pm[1].strip(), {}
            continue
        em = re.match(r"^\s+enums:\s*(.*)$", line)
        if em and prop_name:
            enums = dict((k.strip(), v) for k, v in re.findall(r"([^=\s][^=]*?)=(\d+)", em[1]))
            if prop_name == "pixel blend mode":
                cur["blend_enums"] = enums
            continue
        vm = re.match(r"^\s+value:\s*(\S+)", line)
        if vm and prop_name in ("type", "alpha", "pixel blend mode", "zpos", "COLOR_ENCODING", "COLOR_RANGE"):
            rev = {v: k for k, v in enums.items()}
            cur[prop_name] = rev.get(vm[1], vm[1])
    return planes


def plane_fixes(text):
    """modetest -w arguments that make every overlay plane fully opaque with pre-multiplied blending. mpv draws its OSD
    (and on the H.265 path everything but the video) on an overlay plane and does not set these; a value left behind by
    another program (seen: alpha 3084 of 65535 and "Coverage") makes the OSD nearly invisible."""
    out = []
    for pl in parse_planes_all(text):
        if pl.get("type") != "Overlay":
            continue
        if "alpha" in pl and pl["alpha"] != "65535":
            out.append(f"{pl['id']}:alpha:65535")
        pre = pl["blend_enums"].get("Pre-multiplied")
        if pre is not None and pl.get("pixel blend mode") not in (None, "Pre-multiplied"):
            out.append(f"{pl['id']}:pixel blend mode:{pre}")
    return out


def fix_planes():
    """Run before mpv starts (nobody holds the display then). Returns what was changed, for the log."""
    r = subprocess.run([config.MODETEST, "-p"], capture_output=True, text=True, timeout=8)
    fixes = plane_fixes(r.stdout)
    done = []
    for f in fixes:
        w = subprocess.run([config.MODETEST, "-w", f], capture_output=True, text=True, timeout=8)
        done.append(f + ("" if w.returncode == 0 else f" (failed: {(w.stderr.strip().splitlines() or ['?'])[-1]})"))
    return done


def drm_planes():
    try:
        r = subprocess.run([config.MODETEST, "-p"], capture_output=True, text=True, timeout=8)
        return parse_planes(r.stdout)
    except Exception:
        return []


def drm_modes():
    """Modes per HDMI connector with refresh rates (modetest); falls back to the resolutions in sysfs."""
    try:
        r = subprocess.run([config.MODETEST, "-c"], capture_output=True, text=True, timeout=8)
        found = {k: v for k, v in parse_modetest(r.stdout).items() if "HDMI" in k and v}
        if found:
            return found
    except Exception as e:
        config.log_once("modetest (falling back to the modes in sysfs)", e)
    out = {}
    for p in hdmi_ports():
        modes = []
        for i, m in enumerate(p["all_modes"]):
            mm = re.match(r"^(\d+)x(\d+)(i?)$", m)
            if mm:
                modes.append(
                    {
                        "index": i,
                        "w": int(mm.group(1)),
                        "h": int(mm.group(2)),
                        "interlaced": bool(mm.group(3)),
                        "hz": None,
                        "preferred": False,
                    }
                )
        out[p["name"]] = modes
    return out


VIDEO_PRESETS = {"2160p": (3840, 2160), "1080p": (1920, 1080), "720p": (1280, 720)}
# TV7 and SRG broadcast at 25/50 fps: starting at 50 Hz spares the switch (an mpv restart) on the first channel
START_HZ = 50.0


def start_rate(lst, cands):
    """Of the modes cands (one size), the one to start with when the refresh rate follows the stream: 50 Hz if offered,
    otherwise the rate closest to the display's preferred mode."""
    near = [m for m in cands if m["hz"] is not None and abs(m["hz"] - START_HZ) < 1.0]
    if near:
        return near[0]
    pref = next((m for m in lst if m["preferred"]), None)
    hz = pref["hz"] if pref and pref["hz"] else 60.0
    return min(cands, key=lambda m: abs((m["hz"] or hz) - hz))


def auto_size(lst):
    """Output size for video_mode=auto: 1080p if the display offers it (the channels are at most 1080p, anything larger
    only upscales on the device; the display does that as well), otherwise the display's preferred size."""
    if any((m["w"], m["h"]) == VIDEO_PRESETS["1080p"] and not m["interlaced"] for m in lst):
        return VIDEO_PRESETS["1080p"]
    pref = next((m for m in lst if m["preferred"]), None)
    return (pref["w"], pref["h"]) if pref else None


def resolve_mode(video_mode, port, modes=None):
    """The mode mpv starts with (--drm-mode) plus a note. 'preferred' / 'highest' pass through; a size is resolved to
    the mode INDEX of the connector (a "1920x1080@50" spec could match an interlaced mode first), at the start rate
    (start_rate); the refresh rate then follows the stream (player.match_refresh). The display must offer the size."""
    if video_mode in ("", "auto"):  # 1080p if offered (see auto_size)
        modes = drm_modes() if modes is None else modes
        for lst in [modes[port]] if port and port in modes else list(modes.values()):
            size = auto_size(lst)
            cands = [
                m for m in lst if size and (m["w"], m["h"]) == size and not m["interlaced"] and m["hz"] is not None
            ]
            if cands:
                return str(start_rate(lst, cands)["index"]), ""
        return "preferred", ""
    if video_mode == "highest":
        return "highest", ""
    if video_mode not in VIDEO_PRESETS:
        return "preferred", f"unknown video_mode {video_mode}"
    w, h = VIDEO_PRESETS[video_mode]
    modes = drm_modes() if modes is None else modes
    if port and port in modes:
        lst = modes[port]
    elif port:
        lst = []
    else:  # port auto: first connector that offers the size
        lst = next(
            (x for x in modes.values() if any(m["w"] == w and m["h"] == h and not m["interlaced"] for m in x)), []
        )
    cands = [m for m in lst if m["w"] == w and m["h"] == h and not m["interlaced"]]
    if not cands:
        return "preferred", f"{video_mode} is not offered by the display, using the preferred mode"
    return str(start_rate(lst, cands)["index"]), ""


def current_drm_mode():
    """The output mode chosen to follow the stream's frame rate (mpv is started with it), or "" if none."""
    return _video["override"]


def mode_for_fps(fps, video_mode, port, modes=None):
    """Index of the display mode whose refresh rate equals the stream's frame rate (or a multiple, 25 -> 50, 24 -> 48),
    at the resolution that video_mode asks for (auto: see auto_size). None if the display offers nothing suitable."""
    if not fps or fps < 10:
        return None
    modes = drm_modes() if modes is None else modes
    lists = [modes[port]] if port and port in modes else list(modes.values())
    for lst in lists:
        if video_mode in ("", "auto"):
            size = auto_size(lst)
        elif video_mode in VIDEO_PRESETS:
            size = VIDEO_PRESETS[video_mode]
        else:
            return None  # "highest" is left to mpv
        if not size:
            continue
        cands = [m for m in lst if (m["w"], m["h"]) == size and not m["interlaced"] and m["hz"] is not None]
        for mult in (1, 2, 3, 4):  # exact rate first, then multiples (25 -> 50)
            target = fps * mult
            if mult == 1 and target < 24 - 0.5:
                continue
            hit = [m for m in cands if abs(m["hz"] - target) < 0.6]
            if hit:
                return hit[0]["index"]
    return None


# vo: gpu|drm; pending: chosen without a connected display (plain DRM for now, chosen again once a display is there);
# hw: H.265 is decoded in hardware; mode: the drm-mode mpv was started with; override: the output mode that follows the
# stream's frame rate. Tests and the dev server attach to an mpv started by someone else and set the start values
# (config.VIDEO_START).
_video = {
    "vo": None,
    "pending": "no",
    "hw": config.HW_AVAILABLE,
    "mode": "",
    "override": "",
    "extra": [],
    "msg": "",
}
_video.update(config.VIDEO_START)


def video_state():
    """The video output state (see _video). Callers get the current dict; set_video replaces it as a whole."""
    return _video


def set_video(**values):
    global _video
    _video = {**_video, **values}


def hw_available():
    return video_state()["hw"] == "yes"


def set_mode_override(mode):
    """The output mode mpv gets at its next start (follows the stream's frame rate); "" for none."""
    set_video(override=str(mode))


def _read_all(pattern):
    out = []
    for f in sorted(glob.glob(pattern)):
        try:
            out.append(open(f).read())
        except OSError:
            pass  # a name file that cannot be read: that device has no name
    return "".join(out)


def hdmi_card(port):
    """(DRM device, connector name) of the HDMI connector to use: the given port or the first one. On the Raspberry Pi
    5, card0 is only the render chip (v3d) and the HDMI output is on card1 (vc4), so mpv's default (card0) would not
    work."""
    for c in connectors():
        name = os.path.basename(c)
        card = name.split("-", 1)[0]
        if not port or name[len(card) + 1 :] == port:
            return f"/dev/dri/{card}", name
    return None, None

"""The display: HDMI connectors, output modes, planes, deinterlacing, hardware decoding per device, the output mode that follows the stream, the video output state, the PNG decoder for logos."""

import glob
import os
import re
import subprocess
import zlib

from tv7 import mpvclient

DRM_DIR = os.environ.get("TV7_DRM_DIR", "/sys/class/drm")  # overridable for tests
MODETEST = os.environ.get("TV7_MODETEST", "modetest")


def connectors():
    try:
        return [os.path.join(DRM_DIR, d) for d in sorted(os.listdir(DRM_DIR)) if "-HDMI-A-" in d]
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


def deinterlace_possible(hwdec):
    """Software frames (no, *-copy) and VAAPI frames (mpv deinterlaces them with vavpp) can be deinterlaced. Frames that go straight
    to a display plane (drm on the Raspberry Pi) cannot: a deinterlace filter would turn hardware decoding off."""
    hwdec = hwdec or "no"
    return hwdec == "no" or hwdec.endswith("-copy") or hwdec.startswith("vaapi")


def update_deinterlace(enabled):
    """Apply the deinterlace option (enabled) where the current decoder allows it (see deinterlace_possible). "auto"
    deinterlaces only frames that are interlaced (1080i channels), not the progressive ones (720p50, 1080p); mpv without
    "auto" gets "yes"."""
    try:
        if not (enabled and deinterlace_possible(mpvclient.prop("hwdec-current"))):
            mpvclient.mpv("set_property", "deinterlace", False)
        elif mpvclient.mpv("set_property", "deinterlace", "auto").get("error") != "success":
            mpvclient.mpv("set_property", "deinterlace", True)
    except Exception:
        pass


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
    """`modetest -p`: the planes that show a picture (framebuffer set) with type, alpha, blend mode, zpos, colour encoding/range."""
    return [{k: v for k, v in pl.items() if k != "blend_enums"} for pl in parse_planes_all(text) if pl["fb"]]


def parse_planes_all(text):
    """All planes of `modetest -p` (with or without a picture), with their properties and the enum values of the blend mode."""
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
    """modetest -w arguments that make every overlay plane fully opaque with pre-multiplied blending. mpv draws its OSD (and on
    the H.265 path everything but the video) on an overlay plane and does not set these; a value left behind by another program
    (seen: alpha 3084 of 65535 and "Coverage") makes the OSD nearly invisible."""
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
    r = subprocess.run([MODETEST, "-p"], capture_output=True, text=True, timeout=8)
    fixes = plane_fixes(r.stdout)
    done = []
    for f in fixes:
        w = subprocess.run([MODETEST, "-w", f], capture_output=True, text=True, timeout=8)
        done.append(f + ("" if w.returncode == 0 else f" (failed: {(w.stderr.strip().splitlines() or ['?'])[-1]})"))
    return done


def drm_planes():
    try:
        r = subprocess.run([MODETEST, "-p"], capture_output=True, text=True, timeout=8)
        return parse_planes(r.stdout)
    except Exception:
        return []


def drm_modes():
    """Modes per HDMI connector with refresh rates (modetest); falls back to the resolutions in sysfs."""
    try:
        r = subprocess.run([MODETEST, "-c"], capture_output=True, text=True, timeout=8)
        found = {k: v for k, v in parse_modetest(r.stdout).items() if "HDMI" in k and v}
        if found:
            return found
    except Exception:
        pass
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
START_HZ = 50.0  # TV7 and SRG broadcast at 25/50 fps: starting at 50 Hz spares the switch (an mpv restart) on the first channel


def start_rate(lst, cands):
    """Of the modes cands (one size), the one to start with when the refresh rate follows the stream: 50 Hz if offered, otherwise
    the rate closest to the display's preferred mode."""
    near = [m for m in cands if m["hz"] is not None and abs(m["hz"] - START_HZ) < 1.0]
    if near:
        return near[0]
    pref = next((m for m in lst if m["preferred"]), None)
    hz = pref["hz"] if pref and pref["hz"] else 60.0
    return min(cands, key=lambda m: abs((m["hz"] or hz) - hz))


def auto_size(lst):
    """Output size for video_mode=auto: 1080p if the display offers it (the channels are at most 1080p, anything larger only
    upscales on the device; the display does that as well), otherwise the display's preferred size."""
    if any((m["w"], m["h"]) == VIDEO_PRESETS["1080p"] and not m["interlaced"] for m in lst):
        return VIDEO_PRESETS["1080p"]
    pref = next((m for m in lst if m["preferred"]), None)
    return (pref["w"], pref["h"]) if pref else None


def png_to_bgra(path):
    """Decode a PNG file into premultiplied BGRA, the raw format of mpv's overlay-add. Returns (width, height, bytes)."""
    return png_bytes_to_bgra(open(path, "rb").read())


PNG_MAX_PIXELS = 2_000_000  # logos and the idle logo are far smaller


def png_bytes_to_bgra(data):
    """Decode an 8-bit PNG (grey, RGB, palette, each with or without alpha; not interlaced) into premultiplied BGRA.
    Standard library only: the image has no imaging library."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    pos, idat, w, h, ctype, palette, trns = 8, b"", 0, 0, 0, b"", b""
    while pos < len(data):
        n = int.from_bytes(data[pos : pos + 4], "big")
        kind, body = data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + n]
        pos += 12 + n
        if kind == b"IHDR":
            w, h = int.from_bytes(body[0:4], "big"), int.from_bytes(body[4:8], "big")
            depth, ctype, interlace = body[8], body[9], body[12]
            if depth != 8 or ctype not in (0, 2, 3, 4, 6) or interlace:
                raise ValueError("only 8-bit PNGs without interlacing are supported")
            if not 0 < w * h <= PNG_MAX_PIXELS:
                raise ValueError(f"image too large ({w}x{h})")
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    stride = w * bpp
    need = h * (stride + 1)
    raw = zlib.decompressobj().decompress(idat, need)  # never more than the image needs (no decompression bomb)
    if len(raw) < need:
        raise ValueError("PNG data incomplete")
    prev, out = bytearray(stride), bytearray()
    for y in range(h):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        for x in range(w):
            q = x * bpp
            if ctype == 6:
                r_, g, b_, al = line[q], line[q + 1], line[q + 2], line[q + 3]
            elif ctype == 2:
                r_, g, b_, al = line[q], line[q + 1], line[q + 2], 255
            elif ctype == 3:
                k = line[q]
                r_, g, b_ = palette[3 * k : 3 * k + 3] or b"\0\0\0"
                al = trns[k] if k < len(trns) else 255
            elif ctype == 4:
                r_ = g = b_ = line[q]
                al = line[q + 1]
            else:
                r_ = g = b_ = line[q]
                al = 255
            out += bytes((b_ * al // 255, g * al // 255, r_ * al // 255, al))
        prev = line
    return w, h, bytes(out)


def resolve_mode(video_mode, refresh, port, modes=None):
    """Value for mpv --drm-mode plus a note. 'preferred' / 'highest' pass through; a preset is resolved to the mode INDEX of
    the connector (a "1920x1080@50" spec could match an interlaced mode first). The display must offer the preset."""
    # auto: 1080p if offered (see auto_size); refresh auto: follows the stream later (match_refresh)
    if video_mode in ("", "auto"):
        modes = drm_modes() if modes is None else modes
        for lst in [modes[port]] if port and port in modes else list(modes.values()):
            size = auto_size(lst)
            cands = [
                m for m in lst if size and (m["w"], m["h"]) == size and not m["interlaced"] and m["hz"] is not None
            ]
            if not cands:
                continue
            if refresh in ("", "auto"):
                return str(start_rate(lst, cands)["index"]), ""
            near = [m for m in cands if abs(m["hz"] - float(refresh)) < 1.0]
            if near:
                return str(near[0]["index"]), ""
        if refresh in ("", "auto"):
            return "preferred", ""
        return "preferred", f"{refresh} Hz is not offered by the display, using the preferred mode"
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
    if refresh in ("", "auto"):
        return str(start_rate(lst, cands)["index"]), ""
    note = ""
    near = [m for m in cands if m["hz"] is not None and abs(m["hz"] - float(refresh)) < 1.0]
    if near:
        cands = near
    elif any(m["hz"] is not None for m in cands):
        note = f"{video_mode} is not offered at {refresh} Hz, using another refresh rate"
        cands = sorted(cands, key=lambda m: -(m["hz"] or 0))
    return str(cands[0]["index"]), note


def current_drm_mode():
    """The output mode chosen to follow the stream's frame rate (mpv is started with it), or "" if none."""
    return VIDEO["override"]


def mode_for_fps(fps, video_mode, port, modes=None):
    """Index of the display mode whose refresh rate equals the stream's frame rate (or a multiple, 25 -> 50, 24 -> 48), at the
    resolution that video_mode asks for (auto: see auto_size). None if the display offers nothing suitable."""
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


# vo: gpu|drm; pending: chosen without a connected display (plain DRM for now, chosen again once a display is there); hw: H.265 is
# decoded in hardware; mode: the drm-mode mpv was started with; override: the output mode that follows the stream's frame rate.
# Tests and the dev server attach to an mpv started by someone else and set the start values through TV7_VIDEO.
VIDEO = {
    "vo": None,
    "pending": "no",
    "hw": os.environ.get("TV7_HW_AVAILABLE", "no"),
    "mode": "",
    "override": "",
    "extra": [],
    "msg": "",
}
VIDEO.update(dict(x.split("=", 1) for x in os.environ.get("TV7_VIDEO", "").split() if "=" in x))


def video_state():
    return {k: VIDEO[k] for k in ("vo", "pending", "hw", "mode")}


def hw_available():
    return video_state()["hw"] == "yes"


def set_mode_override(mode):
    """The output mode mpv gets at its next start (follows the stream's frame rate); "" for none."""
    VIDEO["override"] = str(mode)


def pick_hwdec(vo, hardware_decoding, hwdec_help, v4l2_names, arch, render_node):
    """mpv arguments for the video output and the hardware decoding of this device. Returns (arguments, H.265 in hardware, log text).
    - Raspberry Pi 5 and 4, H.265: rpi-hevc-dec (V4L2 stateless, --hwdec=drm). These frames go straight to the display's bottom
      ("primary") plane; the GPU draws everything else (software-decoded channels, menu, technical info, idle logo) on the overlay
      plane above, which fix_planes makes opaque before mpv starts. Measured on the Pi 5: about 0.15 of 4 cores instead of 3.
    - Raspberry Pi 4, H.264: bcm2835-codec (V4L2 stateful, --hwdec=v4l2m2m-copy); "copy" hands the frames back to normal memory, so
      software deinterlacing keeps working. Not tested on a Pi 4.
    - x86 with Intel or AMD graphics: VAAPI for H.264 and H.265, deinterlaced in hardware (vavpp); without the GPU output the frames
      are copied (vaapi-copy). Not tested on a device."""

    def has(name):
        return re.search(rf"^ *{re.escape(name)}( |$)", hwdec_help or "", re.M) is not None

    hevc = "rpi-hevc-dec" in (v4l2_names or "") and has("drm")
    h264 = "bcm2835-codec-decode" in (v4l2_names or "") and has("v4l2m2m-copy")
    vaapi = arch == "x86_64" and bool(render_node) and has("vaapi")
    args = ["--vo=gpu", "--gpu-context=drm"] if vo == "gpu" else ["--vo=drm"]
    if hardware_decoding == "no":
        return args + ["--hwdec=no"], False, "off"
    if vaapi:
        return (
            args + ["--hwdec=vaapi" if vo == "gpu" else "--hwdec=vaapi-copy"],
            False,
            f"VAAPI ({render_node}), all codecs the GPU supports",
        )
    hw, codecs, msg = [], [], []
    if hevc and vo == "gpu":
        args += [
            "--gpu-hwdec-interop=drmprime-overlay",
            "--drm-draw-plane=overlay",
            "--drm-drmprime-video-plane=primary",
        ]
        hw, codecs, msg = ["drm"], ["hevc"], ["H.265 on the Raspberry Pi HEVC decoder"]
    if h264:
        hw, codecs, msg = (
            hw + ["v4l2m2m-copy"],
            codecs + ["h264"],
            msg + ["H.264 on the Raspberry Pi 4 decoder (v4l2m2m-copy, not tested)"],
        )
    if hw:
        return (
            args + [f"--hwdec={','.join(hw)}", f"--hwdec-codecs={','.join(codecs)}"],
            "drm" in hw,
            "; ".join(msg) + "; other channels in software",
        )
    return (
        args + ["--hwdec=auto-safe"],
        False,
        f"mpv auto-safe (Raspberry Pi HEVC decoder: {'yes' if hevc else 'no'}, video output {vo})",
    )


def _read_all(pattern):
    out = []
    for f in sorted(glob.glob(pattern)):
        try:
            out.append(open(f).read())
        except OSError:
            pass
    return "".join(out)


def hdmi_card(port):
    """(DRM device, connector name) of the HDMI connector to use: the given port or the first one. On the Raspberry Pi 5, card0 is
    only the render chip (v3d) and the HDMI output is on card1 (vc4), so mpv's default (card0) would not work."""
    for c in connectors():
        name = os.path.basename(c)
        card = name.split("-", 1)[0]
        if not port or name[len(card) + 1 :] == port:
            return f"/dev/dri/{card}", name
    return None, None

"""Called directly: the parsers of tv7/display.py (DRM planes, output mode resolution) and the PNG decoder (tv7/png.py)."""

import os
import struct
import zlib

import pytest

from fakes import APP_DIR, MODETEST_OUT, ROOTFS
from tv7 import config, display, png

PLANE_HEAD = "Planes:\nid\tcrtc\tfb\tCRTC x,y\tx,y\tgamma size\tpossible crtcs\n"
TYPE = "\t8 type:\n\t\tenums: Overlay=0 Primary=1 Cursor=2\n\t\tvalue: {}\n"
BLEND = "\t39 pixel blend mode:\n\t\tenums: None=2 Pre-multiplied=0 Coverage=1\n\t\tvalue: {}\n"


def test_planes_with_a_picture():
    text = (PLANE_HEAD + "32\t0\t0\t0,0\t\t0,0\t0\t0x1\n  props:\n" + TYPE.format(1)
            + "40\t71\t88\t0,0\t\t0,0\t0\t0x1\n  props:\n" + TYPE.format(0) + "\t38 alpha:\n\t\tvalues: 0 65535\n\t\tvalue: 65535\n"
            + BLEND.format(1) + "\t41 zpos:\n\t\tvalue: 2\n")  # fmt: skip
    assert display.parse_planes(text) == [
        {
            "id": 40,
            "crtc": 71,
            "fb": 88,
            "type": "Overlay",
            "alpha": "65535",
            "pixel blend mode": "Coverage",
            "zpos": "2",
        }
    ]


def test_plane_fixes():
    """Overlay plane left at alpha 3084 / Coverage (seen on the Pi 5): set to opaque and pre-multiplied; others untouched."""
    text = (PLANE_HEAD + "83\t71\t90\t0,0\t\t0,0\t0\t0x1\n  props:\n" + TYPE.format(1) + "\t38 alpha:\n\t\tvalues: 0 65535\n\t\tvalue: 65535\n"
            + "107\t71\t91\t0,0\t\t0,0\t0\t0x1\n  props:\n" + TYPE.format(0) + "\t38 alpha:\n\t\tvalues: 0 65535\n\t\tvalue: 3084\n"
            + BLEND.format(1)
            + "108\t0\t0\t0,0\t\t0,0\t0\t0x1\n  props:\n" + TYPE.format(0) + "\t38 alpha:\n\t\tvalue: 65535\n" + BLEND.format(0))  # fmt: skip
    assert display.plane_fixes(text) == ["107:alpha:65535", "107:pixel blend mode:0"]


@pytest.fixture
def modetest(world, monkeypatch):
    """resolve(mode, port="", without_1080p=False): (mode, note) from the fake modetest."""
    other = world.write_modetest("modetest2", MODETEST_OUT.replace("1920x1080 ", "1680x1050 "))

    def resolve(mode, port="", without_1080p=False):
        monkeypatch.setattr(config, "MODETEST", other if without_1080p else f"{world.tmp}/modetest")
        monkeypatch.setattr(config, "DRM_DIR", world.drm)
        return display.resolve_mode(mode, port)

    return resolve


def test_resolve_sizes(modetest):
    """A size starts at 50 Hz (the channels' rate, so the first channel needs no switch), progressive, not interlaced."""
    assert modetest("1080p", "HDMI-A-1")[0] == "3"
    assert modetest("2160p")[0] == "1"
    mode, note = modetest("720p")
    assert mode == "preferred" and "not offered" in note
    assert modetest("1080p", "HDMI-A-9")[0] == "preferred", "unknown port"
    assert modetest("highest")[0] == "highest"


def test_resolve_auto(modetest):
    """auto means 1080p at 50 Hz when the display offers it, otherwise the display's preferred size at 50 Hz."""
    assert modetest("auto")[0] == "3"
    assert modetest("auto", without_1080p=True)[0] == "1"


def test_idle_logo_bgra():
    """The logo PNG becomes premultiplied BGRA for mpv's overlay-add."""
    w, h, raw = png.png_to_bgra(os.path.join(ROOTFS, "ui-logo.png"))
    px = [raw[i : i + 4] for i in range(0, len(raw), 4)]
    assert (w, h) == (360, 188) and len(raw) == 360 * 188 * 4
    assert px[0] == b"\0\0\0\0", "transparent corner"
    assert any(p[3] == 255 and p[2] > 200 and p[0] < 150 for p in px), "opaque logo colour"
    assert all(max(p[:3]) <= p[3] for p in px), "premultiplied alpha everywhere"


def test_png_decoder_refuses_bad_input():
    with pytest.raises(ValueError, match="not a PNG"):
        png.png_to_bgra(os.path.join(APP_DIR, "config.yaml"))  # the idle screen then stays black

    def chunk(k, d):
        return struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d))

    huge = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 20000, 20000, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(1000000))) + chunk(b"IEND", b""))  # fmt: skip
    with pytest.raises(ValueError, match="too large"):
        png.png_bytes_to_bgra(huge)  # no memory/CPU exhaustion through a logo

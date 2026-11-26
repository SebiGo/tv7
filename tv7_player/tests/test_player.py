"""Starting and supervising mpv (tv7/mpvhost.py, tv7/display.py), called directly: decoder choice per device, audio device,
video output without a display, and the restart loop (with a fake mpv program)."""

import os
import subprocess
import threading

import pytest

from fakes import wait_for
from tv7 import display, mpvhost, system

HELP_PI = "Valid values (with alternative full names):\n  drm (hevc-drm)\n  drm-copy (hevc-drm-copy)\n  v4l2m2m-copy (h264_v4l2m2m-v4l2m2m-copy)"
HELP_X86 = "Valid values (with alternative full names):\n  vaapi (h264-vaapi)\n  vaapi-copy (h264-vaapi-copy)"
PI5 = "rpi-hevc-dec\npispbe"
PI4 = "rpi-hevc-dec\nbcm2835-codec-decode"
RENDER = "/dev/dri/renderD128"


def test_hwdec_pi5():
    """H.265 in hardware on the bottom plane, everything else in software on the overlay plane."""
    a, hw, msg = display.pick_hwdec("gpu", "auto", HELP_PI, PI5, "aarch64", RENDER)
    assert hw and "--hwdec=drm" in a and "--hwdec-codecs=hevc" in a, a
    assert "--drm-draw-plane=overlay" in a and "--drm-drmprime-video-plane=primary" in a, a


def test_hwdec_pi4():
    a, hw, msg = display.pick_hwdec("gpu", "auto", HELP_PI, PI4 + "\nbcm2835-codec-encode", "aarch64", RENDER)
    assert hw and "--hwdec=drm,v4l2m2m-copy" in a and "--hwdec-codecs=hevc,h264" in a, "H.264 on the stateful decoder"
    a, hw, msg = display.pick_hwdec("drm", "auto", HELP_PI, PI4, "aarch64", "")
    assert not hw and "--hwdec=v4l2m2m-copy" in a and "--vo=drm" in a, "without GPU output: no H.265 overlay"
    assert "--drm-draw-plane=overlay" not in a


def test_hwdec_off():
    a, hw, msg = display.pick_hwdec("gpu", "no", HELP_PI, PI4, "aarch64", RENDER)
    assert not hw and "--hwdec=no" in a and msg == "off", a


def test_hwdec_x86():
    a, hw, msg = display.pick_hwdec("gpu", "auto", HELP_X86, "", "x86_64", RENDER)
    assert not hw and "--hwdec=vaapi" in a, "VAAPI with GPU output: vaapi for everything"
    a, hw, msg = display.pick_hwdec("drm", "auto", HELP_X86, "", "x86_64", RENDER)
    assert "--hwdec=vaapi-copy" in a, "DRM output: vaapi-copy"
    a, hw, msg = display.pick_hwdec("gpu", "auto", HELP_X86, "", "x86_64", "")
    assert "--hwdec=auto-safe" in a, "without a render node: mpv auto-safe"


def test_hwdec_unknown_decoder():
    a, hw, msg = display.pick_hwdec("gpu", "auto", HELP_PI, "pispbe", "aarch64", RENDER)
    assert not hw and "--hwdec=auto-safe" in a, a


@pytest.fixture
def aplay(monkeypatch):
    out = "null\nhdmi:CARD=vc4hdmi0,DEV=0\nhdmi:CARD=vc4hdmi1,DEV=0\n"

    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, out if cmd[:2] == ["aplay", "-L"] else "", "")

    monkeypatch.setattr(subprocess, "run", run)


def test_audio_device(aplay, monkeypatch):
    sink = "alsa_output.platform-107c701400.hdmi.hdmi-stereo"
    monkeypatch.setattr(system, "pulse_sinks", lambda: [{"name": sink, "state": "IDLE"}])
    assert mpvhost.audio_args({}, "card1-HDMI-A-1") == [f"--audio-device=pulse/{sink}"], "auto: PulseAudio first"
    assert mpvhost.audio_args({"audio_output": "alsa"}, "card1-HDMI-A-2") == [
        "--audio-device=alsa/hdmi:CARD=vc4hdmi1,DEV=0"
    ]
    monkeypatch.setattr(system, "pulse_sinks", lambda: [])
    assert mpvhost.audio_args({}, "card1-HDMI-A-1") == ["--audio-device=alsa/hdmi:CARD=vc4hdmi0,DEV=0"], "no PulseAudio"
    assert mpvhost.audio_args({"audio_device": "alsa/x"}, "card1-HDMI-A-1") == ["--audio-device=alsa/x"], (
        "explicit wins"
    )


@pytest.fixture
def fake_mpv(tmp_path, monkeypatch):
    """A fake mpv program at tmp_path/mpv (write its script with fake_mpv(text)); no display connected."""
    os.makedirs(tmp_path / "drm" / "card1-HDMI-A-1")
    (tmp_path / "drm" / "card1-HDMI-A-1" / "status").write_text("disconnected\n")
    monkeypatch.setattr(display, "DRM_DIR", str(tmp_path / "drm"))
    monkeypatch.setattr(display, "MODETEST", "true")
    monkeypatch.setattr(mpvhost, "MPV_BIN", str(tmp_path / "mpv"))

    def write(script):
        (tmp_path / "mpv").write_text(script)
        os.chmod(tmp_path / "mpv", 0o755)

    return write


def test_video_output_without_display(fake_mpv):
    fake_mpv("#!/bin/bash\n[ \"$1\" = --hwdec=help ] && printf '  drm (hevc-drm)\\n'\nexit 0\n")
    mpvhost.setup_video({}, [])
    assert display.VIDEO["vo"] == "drm" and display.VIDEO["pending"] == "yes", (
        "plain DRM for now, the choice is pending"
    )
    assert display.hdmi_card("") == ("/dev/dri/card1", "card1-HDMI-A-1"), "Pi 5: card1, not card0"


def test_supervision(fake_mpv, tmp_path, monkeypatch):
    """mpv is started again after every exit, with the current arguments, until it keeps exiting or a stop is asked."""
    log, quit_file = tmp_path / "starts", tmp_path / "quit"
    fake_mpv(
        f'#!/bin/bash\necho "$*" >> {log}\nwhile [ ! -e {quit_file} ]; do sleep 0.05; done\nrm -f {quit_file}\nexit 0\n'
    )
    monkeypatch.setattr(mpvhost, "RESTART_PAUSE_S", 0.05)
    monkeypatch.setattr(mpvhost, "MAX_RESTARTS", 3)
    monkeypatch.setattr(mpvhost, "RESTART_WINDOW_S", 60)
    monkeypatch.setitem(mpvhost.mpv_proc, "stop", False)
    hooks, override = [], {"mode": ""}

    def starts():
        return log.read_text().splitlines() if log.exists() else []

    def quit_and_wait(n):
        quit_file.touch()
        wait_for(lambda: len(starts()) >= n, 5, 0.05)

    def build():
        return ["--common"] + ([f"--drm-mode={override['mode']}"] if override["mode"] else [])

    t = threading.Thread(target=mpvhost.supervise_mpv, args=(build, lambda: hooks.append(1)), daemon=True)
    t.start()
    wait_for(starts, 5, 0.05)
    assert starts() == ["--common"]
    override["mode"] = "1"
    quit_and_wait(2)
    assert starts()[-1:] == ["--common --drm-mode=1"], "started again, with the new output mode"
    quit_and_wait(3)
    assert len(starts()) == 3, "a plain exit (crash): started again"
    assert len(hooks) == 3, "the hook runs before every start"
    quit_and_wait(4)
    quit_and_wait(5)
    t.join(timeout=3)
    assert len(starts()) == 4 and not t.is_alive(), "keeps exiting: no further start after the limit"

    mpvhost.mpv_proc["stop"] = True
    t2 = threading.Thread(target=mpvhost.supervise_mpv, args=(lambda: ["--x"], lambda: None), daemon=True)
    t2.start()
    t2.join(timeout=2)
    assert not t2.is_alive() and len(starts()) == 4, "stop requested: mpv is not started any more"

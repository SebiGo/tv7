"""Tests for starting and supervising mpv (tv7/mpvhost.py, tv7/display.py): decoder choice per device, audio device, video output without a display,
and the restart loop (with a fake mpv program). Run: python3 tests/test_player.py (also run by test_control.py)."""
import os
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "rootfs"))
from tv7 import display, mpvhost, system  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    fails += (not cond)
    print(("OK  " if cond else "FAIL"), name, detail)


# --- Decoder choice per device -------------------------------------------------------
HELP_PI = "Valid values (with alternative full names):\n  drm (hevc-drm)\n  drm-copy (hevc-drm-copy)\n  v4l2m2m-copy (h264_v4l2m2m-v4l2m2m-copy)"
HELP_X86 = "Valid values (with alternative full names):\n  vaapi (h264-vaapi)\n  vaapi-copy (h264-vaapi-copy)"
a, hw, msg = display.pick_hwdec("gpu", "auto", HELP_PI, "rpi-hevc-dec\npispbe", "aarch64", "/dev/dri/renderD128")
check("H1 Pi 5: H.265 in hardware on the bottom plane, everything else in software on the overlay plane",
      hw and "--hwdec=drm" in a and "--hwdec-codecs=hevc" in a and "--drm-draw-plane=overlay" in a and "--drm-drmprime-video-plane=primary" in a, str(a))
a, hw, msg = display.pick_hwdec("gpu", "auto", HELP_PI, "rpi-hevc-dec\nbcm2835-codec-decode\nbcm2835-codec-encode", "aarch64", "/dev/dri/renderD128")
check("H2 Pi 4: H.265 on the HEVC decoder, H.264 on the stateful decoder with copy", hw and "--hwdec=drm,v4l2m2m-copy" in a and "--hwdec-codecs=hevc,h264" in a, str(a))
a, hw, msg = display.pick_hwdec("drm", "auto", HELP_PI, "rpi-hevc-dec\nbcm2835-codec-decode", "aarch64", "")
check("H3 Pi 4 without GPU output: no H.265 overlay, H.264 still on the decoder", not hw and "--hwdec=v4l2m2m-copy" in a and "--vo=drm" in a
      and "--drm-draw-plane=overlay" not in a, str(a))
a, hw, msg = display.pick_hwdec("gpu", "no", HELP_PI, "rpi-hevc-dec\nbcm2835-codec-decode", "aarch64", "/dev/dri/renderD128")
check("H4 hardware_decoding=no: software only", not hw and "--hwdec=no" in a and msg == "off", str(a))
a, hw, msg = display.pick_hwdec("gpu", "auto", HELP_X86, "", "x86_64", "/dev/dri/renderD128")
check("H5 x86 with VAAPI and GPU output: vaapi for everything", not hw and "--hwdec=vaapi" in a, str(a))
a, hw, msg = display.pick_hwdec("drm", "auto", HELP_X86, "", "x86_64", "/dev/dri/renderD128")
check("H6 x86 with VAAPI, DRM output: vaapi-copy", "--hwdec=vaapi-copy" in a, str(a))
a, hw, msg = display.pick_hwdec("gpu", "auto", HELP_X86, "", "x86_64", "")
check("H7 x86 without a render node: mpv auto-safe", "--hwdec=auto-safe" in a, str(a))
a, hw, msg = display.pick_hwdec("gpu", "auto", HELP_PI, "pispbe", "aarch64", "/dev/dri/renderD128")
check("H8 no known decoder: mpv auto-safe", not hw and "--hwdec=auto-safe" in a, str(a))

# --- Audio device ------------------------------------------------------------------
APLAY = "null\nhdmi:CARD=vc4hdmi0,DEV=0\nhdmi:CARD=vc4hdmi1,DEV=0\n"
real_run, real_sinks = subprocess.run, system.pulse_sinks
subprocess.run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, APLAY if cmd[:2] == ["aplay", "-L"] else "", "")
try:
    system.pulse_sinks = lambda: [{"name": "alsa_output.platform-107c701400.hdmi.hdmi-stereo", "state": "IDLE"}]
    check("A1 auto: PulseAudio HDMI sink first", mpvhost.audio_args({}, "card1-HDMI-A-1") == ["--audio-device=pulse/alsa_output.platform-107c701400.hdmi.hdmi-stereo"])
    check("A2 alsa: the ALSA device of the connector (HDMI-A-2 = vc4hdmi1)",
          mpvhost.audio_args({"audio_output": "alsa"}, "card1-HDMI-A-2") == ["--audio-device=alsa/hdmi:CARD=vc4hdmi1,DEV=0"])
    system.pulse_sinks = lambda: []
    check("A3 auto without PulseAudio: ALSA", mpvhost.audio_args({}, "card1-HDMI-A-1") == ["--audio-device=alsa/hdmi:CARD=vc4hdmi0,DEV=0"])
    check("A4 explicit audio_device wins", mpvhost.audio_args({"audio_device": "alsa/x"}, "card1-HDMI-A-1") == ["--audio-device=alsa/x"])
finally:
    subprocess.run, system.pulse_sinks = real_run, real_sinks

# --- Video output without a display ------------------------------------------------------
tmp = tempfile.mkdtemp()
os.makedirs(f"{tmp}/drm/card1-HDMI-A-1")
open(f"{tmp}/drm/card1-HDMI-A-1/status", "w").write("disconnected\n")
open(f"{tmp}/mpv", "w").write("#!/bin/bash\n[ \"$1\" = --hwdec=help ] && printf '  drm (hevc-drm)\\n'\nexit 0\n")
os.chmod(f"{tmp}/mpv", 0o755)
display.DRM_DIR, mpvhost.MPV_BIN, display.MODETEST = f"{tmp}/drm", f"{tmp}/mpv", "true"
mpvhost.setup_video({}, [])
check("V1 no display at start: plain DRM for now, the choice is pending", display.VIDEO["vo"] == "drm" and display.VIDEO["pending"] == "yes", str(display.video_state()))
check("V2 device card of the HDMI connector (Pi 5: card1, not card0)", display.hdmi_card("") == ("/dev/dri/card1", "card1-HDMI-A-1"))

# --- Supervision: mpv is started again after every exit ----------------------------------
log = f"{tmp}/starts"
open(f"{tmp}/mpv", "w").write(f"#!/bin/bash\necho \"$*\" >> {log}\nwhile [ ! -e {tmp}/quit ]; do sleep 0.05; done\nrm -f {tmp}/quit\nexit 0\n")
mpvhost.RESTART_PAUSE_S, mpvhost.MAX_RESTARTS, mpvhost.RESTART_WINDOW_S = 0.05, 3, 60
hooks, override = [], {"mode": ""}
starts = lambda: open(log).read().splitlines() if os.path.exists(log) else []


def quit_and_wait(n):
    open(f"{tmp}/quit", "w").close()
    for _ in range(100):
        if len(starts()) >= n:
            return
        time.sleep(0.05)


t = threading.Thread(target=mpvhost.supervise_mpv, args=(lambda: ["--common"] + ([f"--drm-mode={override['mode']}"] if override["mode"] else []),
                                                    lambda: hooks.append(1)), daemon=True)
t.start()
for _ in range(100):
    if starts():
        break
    time.sleep(0.05)
check("S1 mpv started with its arguments", starts() == ["--common"], str(starts()))
override["mode"] = "1"
quit_and_wait(2)
check("S2 after an exit mpv is started again, with the new output mode", starts()[-1:] == ["--common --drm-mode=1"], str(starts()))
quit_and_wait(3)
check("S3 a plain exit (crash): started again", len(starts()) == 3, str(starts()))
check("S4 the hook runs before every start", len(hooks) == 3, str(len(hooks)))
quit_and_wait(4)
quit_and_wait(5)
t.join(timeout=3)
check("S5 keeps exiting: no further start after the limit", len(starts()) == 4 and not t.is_alive(), str(len(starts())))
mpvhost.mpv_proc["stop"] = True
t2 = threading.Thread(target=mpvhost.supervise_mpv, args=(lambda: ["--x"], lambda: None), daemon=True)
t2.start()
t2.join(timeout=2)
check("S6 stop requested: mpv is not started any more", not t2.is_alive() and len(starts()) == 4)

print("FAILURES:", fails)
sys.exit(1 if fails else 0)

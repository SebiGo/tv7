"""Starting and supervising mpv: video output, hardware decoding, output mode and audio device, restarts, clean stop."""

import glob
import os
import subprocess
import time

from tv7 import config, display, hwdec, mpvclient, png, settings

# control.py starts mpv itself (run.sh only starts control.py): it chooses the video output, hardware decoding, output
# mode and audio device, starts mpv and starts it again whenever it ends (a crash must not leave the player dead; a
# channel start asks for a restart with "quit" to change the output mode or to choose the video output once a display is
# there).
MPV_BIN = "mpv"
WAIT_HDMI_S = 60.0  # wait this long for a display at start
RESTART_PAUSE_S = 1.0
# in RESTART_WINDOW_S: then mpv cannot start at all, stop trying
MAX_RESTARTS = 8
RESTART_WINDOW_S = 60.0
IDLE_LOGO_RAW = "/tmp/tv7-idle.bgra"
mpv_proc = {"p": None, "stop": False}


def probe_gpu(drm_args):
    """Does the GPU output (OpenGL on the DRM display) work? Tried in a short throw-away mpv: a failed GPU start inside
    the real mpv leaves the display locked, so a fallback inside the same process would fail too."""
    try:
        return (
            subprocess.run(
                [
                    MPV_BIN,
                    "--no-config",
                    "--vo=gpu",
                    "--gpu-context=drm",
                    "--no-audio",
                    "--frames=2",
                    "--really-quiet",
                    *drm_args,
                    "av://lavfi:testsrc=size=640x360:rate=25",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
            ).returncode
            == 0
        )
    except Exception:
        return False


def setup_video(opts, drm_args):
    """Video output, hardware decoding and output mode. Without a display the GPU cannot be probed and there are no
    modes yet: the choice stays pending (plain DRM) and is made again before mpv restarts once a display is there."""
    pending = "no"
    if not display.hdmi_ok():
        vo, pending = "drm", "yes"
    else:
        vo = "gpu" if probe_gpu(drm_args) else "drm"
    try:
        help_text = subprocess.run([MPV_BIN, "--hwdec=help"], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        help_text = ""
    render = sorted(glob.glob("/dev/dri/renderD*"))
    extra, hw, msg = hwdec.pick_hwdec(
        vo,
        help_text,
        display._read_all("/sys/class/video4linux/*/name"),
        os.uname().machine,
        render[0] if render else "",
    )
    port = "" if opts.get("hdmi_port", "auto") == "auto" else opts.get("hdmi_port")
    mode, note = display.resolve_mode(str(opts.get("video_mode", "auto")), port)
    display.set_video(vo=vo, pending=pending, hw="yes" if hw else "no", mode=mode, extra=extra, msg=msg)
    config.log_line(f"Video mode: {opts.get('video_mode', 'auto')} -> drm-mode={mode}" + (f" ({note})" if note else ""))
    config.log_line(
        f"Video output: {vo}"
        + (" for now (no display connected; chosen again when one is)" if pending == "yes" else "")
    )
    config.log_line(f"Hardware decoding: {msg}")


def pulse_sinks():
    """PulseAudio sinks of Home Assistant's audio service (empty if pactl or the service is missing)."""
    try:
        r = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=4)
        return [
            {"name": p[1], "state": p[-1]} for p in (line.split("\t") for line in r.stdout.splitlines()) if len(p) >= 2
        ]
    except Exception:
        return []


def audio_args(connector):
    """Audio device. Home Assistant's audio service (PulseAudio) may already own the HDMI ALSA card ("Device or resource
    busy"), so a PulseAudio HDMI sink comes first, then the ALSA device of the connector (HDMI-A-1 = vc4hdmi0, HDMI-A-2
    = vc4hdmi1), then any ALSA HDMI device; otherwise mpv chooses."""
    pulse = next((f"pulse/{x['name']}" for x in pulse_sinks() if "hdmi" in x["name"].lower()), "")
    try:
        aplay = subprocess.run(["aplay", "-L"], capture_output=True, text=True, timeout=5).stdout.splitlines()
    except Exception:
        aplay = []
    n = connector.rsplit("-", 1)[-1] if connector else ""
    mine = f"hdmi:CARD=vc4hdmi{int(n) - 1},DEV=0" if n.isdigit() and int(n) >= 1 else None
    alsa = f"alsa/{mine}" if mine and mine in aplay else next((f"alsa/{d}" for d in aplay if d.startswith("hdmi:")), "")
    dev = pulse or alsa
    config.log_line(f"Audio device: {dev}" if dev else "No HDMI audio device found, mpv chooses")
    return [f"--audio-device={dev}"] if dev else []


def mpv_base_args(opts, drm_args, connector):
    """Everything except the video output, decoding and output mode (VIDEO)."""
    args = [
        f"--input-ipc-server={mpvclient.SOCK}",
        "--idle=yes",
        "--force-window=yes",
        "--no-input-terminal",
        "--term-osd=no",
        "--term-status-msg=",
        "--msg-level=all=warn,ao=v,alsa=v,vo=info,cplayer=info",
        "--cache=no",
        "--demuxer-readahead-secs=2",
        "--ytdl=no",  # no yt-dlp lookup for web URLs: only Init7 streams are played
        "--script-opts-append=osc-idlescreen=no",  # mpv's own idle screen is replaced by the TV7 logo (tv7-idle.lua)
        "--deinterlace=no",  # switched on per channel (update_deinterlace)
        "--sid=no",
        "--volume=100",
        "--ao=pulse,alsa",
        *drm_args,
    ]
    if opts.get("debug"):
        args.append("--msg-level=all=v")  # option debug: mpv's detailed log in the app log
    if opts.get("decode_speed") == "fast":  # skip the in-loop filter of non-reference frames: less CPU
        args += ["--vd-lavc-skiploopfilter=nonref", "--vd-lavc-fast"]
    if opts.get("audio_channels") == "stereo":
        args.append("--audio-channels=stereo")
    try:
        w, h, px = png.png_to_bgra(config.UI_LOGO)  # idle screen: the TV7 logo while nothing plays
        with open(IDLE_LOGO_RAW, "wb") as f:
            f.write(px)
        args += [
            f"--script={os.path.join(config.ROOT, 'tv7-idle.lua')}",
            f"--script-opts-append=tv7idle-file={IDLE_LOGO_RAW}",
            f"--script-opts-append=tv7idle-w={w}",
            f"--script-opts-append=tv7idle-h={h}",
        ]
    except Exception as e:
        config.log_line(f"Idle screen: the logo could not be prepared ({e}), the screen stays black")
    return args + audio_args(connector)


def wait_hdmi():
    if display.hdmi_ok() or not display.connectors():
        return
    config.log_line(f"Waiting up to {WAIT_HDMI_S:g}s for an HDMI display ...")
    end = time.time() + WAIT_HDMI_S
    while time.time() < end and not mpv_proc["stop"]:
        if display.hdmi_ok():
            config.log_line("HDMI connected")
            return
        time.sleep(1)
    config.log_line(
        "No HDMI display detected. The player starts anyway; check the cable, switch the TV on and to this input."
    )


def before_start(opts, drm_args):
    """Before every start of mpv: make a pending video output choice once a display is there, and make the overlay
    planes opaque (mpv draws its OSD there and does not set their alpha; a value another program left there makes the
    OSD nearly invisible)."""
    if display.video_state()["pending"] == "yes" and display.hdmi_ok():
        setup_video(opts, drm_args)
    try:
        done = display.fix_planes()
        if done:
            config.log_line("Display planes set to opaque, pre-multiplied: " + ", ".join(done))
    except Exception as e:
        config.log_line(f"Display planes not checked: {e}")


def supervise_mpv(build_args, before, sleep=time.sleep):
    """Start mpv and start it again after every exit, until stop is requested. More than MAX_RESTARTS exits within
    RESTART_WINDOW_S: mpv cannot start at all, give up (the web UI keeps running)."""
    restarts, window = 0, time.time()
    while not mpv_proc["stop"]:
        before()
        args = build_args()
        p = mpv_proc["p"] = subprocess.Popen([MPV_BIN, *args])
        code = p.wait()
        if mpv_proc["stop"]:
            return
        now = time.time()
        if now - window > RESTART_WINDOW_S:
            restarts, window = 0, now
        restarts += 1
        if restarts > MAX_RESTARTS:
            config.log_line(f"mpv keeps exiting (last exit code {code}); not restarting it any more.")
            return
        config.log_line(f"mpv exited (code {code}); starting it again.")
        sleep(RESTART_PAUSE_S)


def stop_app(*_):
    """SIGTERM from the Supervisor (app stop): end mpv and exit cleanly (code 0)."""
    mpv_proc["stop"] = True
    p = mpv_proc["p"]
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    config.log_line("Stopping the app")
    os._exit(0)


def run_player():
    """Production: start and supervise mpv (control.py was started without a socket path)."""
    opts = settings.read_options()
    if os.path.exists("/run/audio/pulse.sock"):  # Home Assistant's PulseAudio does not set PULSE_SERVER for the app
        os.environ["PULSE_SERVER"] = "unix:/run/audio/pulse.sock"
    try:  # never let a PulseAudio client start its own daemon (it would grab the card)
        os.makedirs("/root/.config/pulse", exist_ok=True)
        with open("/root/.config/pulse/client.conf", "w") as f:
            f.write("autospawn = no\n")
    except Exception as e:
        config.log_once("PulseAudio client configuration", e)
    wait_hdmi()
    port = "" if opts.get("hdmi_port", "auto") == "auto" else opts.get("hdmi_port")
    device, connector = display.hdmi_card(port)
    drm_args = ([f"--drm-connector={port}"] if port else []) + ([f"--drm-device={device}"] if device else [])
    if device:
        config.log_line(f"DRM device: {device} ({connector})")
    setup_video(opts, drm_args)
    base = mpv_base_args(opts, drm_args, connector)

    def build():
        video = display.video_state()
        args = base + video["extra"] + [f"--drm-mode={video['mode']}"]
        if video["override"]:
            config.log_line(f"Output mode override (follows the stream's frame rate): drm-mode={video['override']}")
            args.append(f"--drm-mode={video['override']}")
        return args

    supervise_mpv(build, lambda: before_start(opts, drm_args))
    while True:  # mpv gave up: keep the web UI and API running
        time.sleep(3600)

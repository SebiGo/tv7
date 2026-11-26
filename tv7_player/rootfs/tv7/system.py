"""The device: CPU load, temperature, clock, memory, audio devices, the environment and nerd mode views."""

import glob
import json
import os
import subprocess
import time

from tv7 import cec, config, display, mpvclient, player, settings


def alsa_status():
    """Who holds the ALSA playback devices? (owner_pid is in the host PID namespace)"""
    out = []
    for f in sorted(glob.glob("/proc/asound/card*/pcm*p/sub0/status")):
        try:
            out.append(f.split("/proc/asound/")[1].split("/sub0")[0] + ": " + " ".join(open(f).read().split()))
        except Exception:
            pass
    return out


def pulse_sinks():
    """PulseAudio sinks of Home Assistant's audio service (empty if pactl or the service is missing)."""
    try:
        r = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=4)
        return [
            {"name": p[1], "state": p[-1]} for p in (line.split("\t") for line in r.stdout.splitlines()) if len(p) >= 2
        ]
    except Exception:
        return []


def environment():
    ports = display.hdmi_ports()
    devices = [
        {"name": d.get("name", ""), "description": d.get("description", "")}
        for d in (mpvclient.prop("audio-device-list") or [])
    ]
    try:
        opts = json.load(open(config.OPTIONS_FILE))
        for k in settings.OBSOLETE_OPTIONS:  # options of older versions (e.g. a former api_token)
            opts.pop(k, None)
    except Exception:
        opts = {}
    return {
        "hdmi_ports": ports,
        "audio": {
            "devices": devices,
            "pulse_sinks": pulse_sinks(),
            "current_device": mpvclient.prop("audio-device"),
            "current_ao": mpvclient.prop("current-ao"),
        },
        "video": {
            "hwdec": mpvclient.prop("hwdec-current"),
            "codec": mpvclient.prop("video-codec"),
            "vo": mpvclient.prop("current-vo"),
            "width": mpvclient.prop("osd-width"),
            "height": mpvclient.prop("osd-height"),
            "fps": mpvclient.prop("display-fps"),
        },
        "drm_modes": {
            k: [f"{m['w']}x{m['h']}{'i' if m['interlaced'] else ''}" + (f"@{m['hz']:g}" if m["hz"] else "") for m in v]
            for k, v in display.drm_modes().items()
        },
        "options": opts,
        "cec": dict(cec.cec_state),
        "choices": {
            "hdmi_port": ["auto"] + [p["name"] for p in ports],
            "audio_output": ["auto", "pulseaudio", "alsa"],
            "audio_device": [
                d["name"]
                for d in devices
                if d["name"].split("/")[0] in ("pulse", "alsa") and "hdmi" in d["name"].lower()
            ],
        },
    }


_cpu_prev = {}


def _mpv_pid():
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                if open(f"/proc/{d}/comm").read().strip() == "mpv":
                    return int(d)
            except OSError:
                pass
    return None


def system_load():
    """CPU load of the whole system and of mpv since the previous call, plus the SoC temperature."""
    out = {"cores": os.cpu_count() or 1, "total": None, "mpv": None, "temp_c": None}
    try:
        f = [int(x) for x in open("/proc/stat").readline().split()[1:]]
        total, idle = sum(f), f[3] + (f[4] if len(f) > 4 else 0)
        pid = _mpv_pid()
        mj = None
        if pid:
            p = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
            mj = int(p[11]) + int(p[12])  # utime + stime
        now, prev = time.time(), _cpu_prev
        if prev and now - prev["t"] >= 0.5:
            dt_total, dt_idle = total - prev["total"], idle - prev["idle"]
            if dt_total > 0:
                out["total"] = round(100.0 * (dt_total - dt_idle) / dt_total, 1)
            if mj is not None and prev.get("mj") is not None and prev.get("pid") == pid:
                # % of ONE core
                out["mpv"] = round(100.0 * (mj - prev["mj"]) / (os.sysconf("SC_CLK_TCK") * (now - prev["t"])), 1)
            _cpu_prev.update(t=now, total=total, idle=idle, mj=mj, pid=pid, last=dict(out))
        elif prev:
            out.update({k: v for k, v in prev.get("last", {}).items() if k in ("total", "mpv")})
        else:
            _cpu_prev.update(t=now, total=total, idle=idle, mj=mj, pid=pid, last={})
    except Exception:
        pass
    try:
        out["temp_c"] = round(int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000.0, 1)
    except Exception:
        pass
    return out


CPUFREQ_DIR = os.environ.get("TV7_CPUFREQ_DIR", "/sys/devices/system/cpu/cpu0/cpufreq")


def _read(path):
    try:
        return open(path).read().strip()
    except OSError:
        return None


def cpu_clock():
    """Current and maximum CPU clock in MHz (cpufreq of cpu0, all cores share one clock on the Pi)."""
    cur, mx = _read(f"{CPUFREQ_DIR}/scaling_cur_freq"), _read(f"{CPUFREQ_DIR}/cpuinfo_max_freq")
    return {
        "mhz": round(int(cur) / 1000) if cur and cur.isdigit() else None,
        "max_mhz": round(int(mx) / 1000) if mx and mx.isdigit() else None,
        "governor": _read(f"{CPUFREQ_DIR}/scaling_governor"),
    }


def memory():
    out = {}
    try:
        for line in open("/proc/meminfo"):
            k, v = line.split(":", 1)
            if k in ("MemTotal", "MemAvailable"):
                out[k] = int(v.split()[0]) // 1024  # MiB
    except Exception:
        pass
    return {"total_mib": out.get("MemTotal"), "available_mib": out.get("MemAvailable")}


def nerd():
    """All technical details at once (mpv properties, DRM output, system); read-only."""
    p = {
        k: mpvclient.prop(k)
        for k in (
            "video-codec",
            "video-format",
            "video-params",
            "video-bitrate",
            "container-fps",
            "estimated-vf-fps",
            "hwdec",
            "hwdec-current",
            "current-vo",
            "deinterlace",
            "vf",
            "frame-drop-count",
            "decoder-frame-drop-count",
            "vo-delayed-frame-count",
            "mistimed-frame-count",
            "avsync",
            "total-avsync-change",
            "audio-codec",
            "audio-codec-name",
            "audio-params",
            "audio-out-params",
            "audio-bitrate",
            "audio-device",
            "current-ao",
            "volume",
            "mute",
            "display-fps",
            "osd-width",
            "osd-height",
            "path",
            "file-format",
            "mpv-version",
            "ffmpeg-version",
            "pid",
            "options/drm-device",
            "options/drm-connector",
            "options/drm-mode",
            "options/drm-draw-plane",
            "options/drm-drmprime-video-plane",
            "options/gpu-hwdec-interop",
            "options/hwdec-codecs",
        )
    }
    vp, ap, aop = p["video-params"] or {}, p["audio-params"] or {}, p["audio-out-params"] or {}
    try:
        load = [float(x) for x in open("/proc/loadavg").read().split()[:3]]
    except Exception:
        load = None
    return {
        "playing": mpvclient.playing(),
        "channel": player.current["name"],
        "source": player.current["source"],
        "url": p["path"],
        "format": p["file-format"],
        "video": {
            "codec": p["video-codec"],
            "format": p["video-format"],
            "pixelformat": vp.get("pixelformat"),
            "hw_pixelformat": vp.get("hw-pixelformat"),
            "w": vp.get("w"),
            "h": vp.get("h"),
            "colormatrix": vp.get("colormatrix"),
            "primaries": vp.get("primaries"),
            "gamma": vp.get("gamma"),
            "fps": p["container-fps"],
            "fps_estimated": p["estimated-vf-fps"],
            "bitrate": p["video-bitrate"],
            "hwdec": ",".join(p["hwdec"]) if isinstance(p["hwdec"], list) else p["hwdec"],
            "hwdec_current": p["hwdec-current"],
            "deinterlace": p["deinterlace"],
            "filters": [f.get("name") for f in (p["vf"] or [])],
        },
        "frames": {
            "dropped_vo": p["frame-drop-count"],
            "dropped_decoder": p["decoder-frame-drop-count"],
            "delayed": p["vo-delayed-frame-count"],
            "mistimed": p["mistimed-frame-count"],
            "avsync": p["avsync"],
            "avsync_change": p["total-avsync-change"],
        },
        "audio": {
            "codec": p["audio-codec"],
            "codec_name": p["audio-codec-name"],
            "samplerate": ap.get("samplerate"),
            "channels": ap.get("hr-channels") or ap.get("channels"),
            "format": ap.get("format"),
            "out_samplerate": aop.get("samplerate"),
            "out_channels": aop.get("hr-channels") or aop.get("channels"),
            "out_format": aop.get("format"),
            "bitrate": p["audio-bitrate"],
            "device": p["audio-device"],
            "ao": p["current-ao"],
            "volume": p["volume"],
            "mute": p["mute"],
        },
        "output": {
            "vo": p["current-vo"],
            "w": p["osd-width"],
            "h": p["osd-height"],
            "hz": p["display-fps"],
            "drm_device": p["options/drm-device"],
            "drm_connector": p["options/drm-connector"],
            "drm_mode": p["options/drm-mode"],
            "drm_mode_override": display.current_drm_mode() or None,
            "draw_plane": p["options/drm-draw-plane"],
            "video_plane": p["options/drm-drmprime-video-plane"],
            "hwdec_interop": p["options/gpu-hwdec-interop"],
            "hwdec_codecs": p["options/hwdec-codecs"],
            "hdmi": display.hdmi_status(),
            "planes": display.drm_planes(),
        },
        "system": {**system_load(), "clock": cpu_clock(), "loadavg": load, "memory": memory()},
        "mpv": {"version": p["mpv-version"], "ffmpeg": p["ffmpeg-version"], "pid": p["pid"]},
        "app": {
            "version": config.app_version(),
            "hw_available": display.hw_available(),
            "video": display.video_state(),
        },
        "log": mpvclient.mpv_log(),
        "cec": {"state": cec.cec_state["state"], "device": cec.cec_state["device"], "log": cec.cec_log()},
    }


def dri_devices():
    try:
        return sorted(os.listdir("/dev/dri"))
    except OSError:
        return []

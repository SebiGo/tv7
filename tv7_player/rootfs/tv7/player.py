"""What plays: channel start and stop on one worker thread, mpv restarts, the HDMI watcher, the stop without operation."""

import concurrent.futures
import os
import threading
import time

from tv7 import cec, config, display, init7, mpvclient, settings

START_TIMEOUT = float(os.environ.get("TV7_START_TIMEOUT", "10"))
MODE_WAIT_S = float(os.environ.get("TV7_MODE_WAIT_S", "25"))
current = {"pk": None, "name": None, "source": None}  # what was started last (shown by /status and the web UI)
last_start = {}  # result and log of the last channel start (support text)


def stop_playback(wait=True):
    return player(_stop_playback, wait=wait)


def _stop_playback():
    current.update(pk=None, name=None, source=None)
    hdmi_stopped.clear()
    return mpvclient.mpv("stop")


last_played = {}  # last channel started (play key)


def restart_mpv(log, reason):
    """Quit mpv; the supervision starts it again (with the current video output and output mode). Waits for the new process,
    restores volume/mute."""
    log.append(f"{reason} (mpv restarts)")
    keep = {"volume": mpvclient.prop("volume"), "mute": mpvclient.prop("mute")}
    old_pid = mpvclient.prop("pid")
    try:
        mpvclient.mpv("quit")
    except Exception:
        pass
    end = time.time() + MODE_WAIT_S
    while time.time() < end:  # wait for the NEW mpv (different pid) to answer
        time.sleep(0.4)
        pid = mpvclient.prop("pid")
        if pid is not None and pid != old_pid:
            break
    if mpvclient.prop("pid") is None:
        raise RuntimeError("mpv did not come back after the restart")
    for k, v in settings.current_values().items():  # live settings are not in the new mpv's command line
        if k in ("audio_language", "audio_channels"):
            settings.apply_live(k, v)
    if keep["volume"] is not None:
        mpvclient.mpv("set_property", "volume", keep["volume"])
    if keep["mute"]:
        mpvclient.mpv("set_property", "mute", True)


# Everything that changes what plays (start, stop, automatic stops and resumes, configuration switches) runs on one thread, in
# the order it was asked for, so these actions never overlap. Callers wait for the result or not; code holding _menu_lock never
# waits (the worker takes that lock to update the banner).
_player_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="player")


def player(fn, *args, wait=True):
    if threading.current_thread().name.startswith("player"):
        return fn(*args)

    def run():
        try:
            return fn(*args)
        finally:
            mpvclient.changed()  # what plays may have changed: tell /events

    if wait:
        return _player_pool.submit(run).result()

    def logged():
        try:
            run()
        except Exception as e:
            config.log_line(f"Player action {getattr(fn, '__name__', fn)}: {type(e).__name__}: {e}")

    return _player_pool.submit(logged)


def start(ch, source):
    return player(_start_channel, ch, source)


def _start_channel(ch, source):
    res = _start(ch, source)
    if res.get("ok"):
        last_played.update(pk=ch["pk"], source=res.get("source"))
        cec.cec_away["since"] = None
        cec.cec_resume.clear()
        cec.cec_active_source()  # TV/projector and receiver switch to the app; its remote keys come here
    return res


def _start(ch, source):
    log = []
    if display.connectors() and not display.hdmi_ok():
        log.append("HDMI: no display connected (cable, TV off or on another input?); starting anyway")
    # chosen without a display: choose the video output now
    if display.connectors() and display.hdmi_ok() and display.video_state()["pending"] == "yes":
        restart_mpv(log, "display connected: choosing the video output again")
    for src in {"auto": ["multicast", "hls"], "multicast": ["multicast"], "hls": ["hls"]}[source]:
        try:
            url = init7.stream_url(ch, src)
        except KeyError as e:
            log.append(f"{src}: {e}")
            continue
        for attempt in (1, 2):
            # every channel starts without subtitles (track picker turns them on)
            mpvclient.mpv("set_property", "sid", "no")
            mpvclient.mpv("loadfile", url, "replace")
            end = time.time() + START_TIMEOUT
            while time.time() < end:
                if mpvclient.playing():
                    log.append(f"{src}: started (attempt {attempt})")
                    current.update(pk=ch["pk"], name=ch["name"], source=src)
                    if display.match_refresh(log):  # mpv restarted with a new output mode: play the channel again
                        mpvclient.mpv("loadfile", url, "replace")
                        t_end = time.time() + START_TIMEOUT
                        while time.time() < t_end and not mpvclient.playing():
                            time.sleep(0.5)
                    display.update_deinterlace()
                    return {"ok": True, "channel": ch["name"], "source": src, "log": log}
                if (
                    display.connectors()
                    and not display.hdmi_ok()
                    and (mpvclient.prop("time-pos") or 0) > 0
                    and not mpvclient.prop("video-codec")
                ):
                    # The stream runs (time advances) but mpv has no picture output: no display on HDMI. Other attempts or
                    # sources would end the same way.
                    log.append(f"{src}: the stream is received, but no display is connected to HDMI (no picture)")
                    try:
                        mpvclient.mpv("stop")
                    except Exception:
                        pass
                    return {"ok": False, "channel": ch["name"], "log": log, "reason": "no_display"}
                time.sleep(0.5)
            log.append(f"{src}: attempt {attempt} did not start within {START_TIMEOUT:g} s")
    return {"ok": False, "channel": ch["name"], "log": log}


HDMI_OFF_S = float(os.environ.get("TV7_HDMI_OFF_S", "15"))  # display gone this long: stop playback
HDMI_BACK_S = float(os.environ.get("TV7_HDMI_BACK_S", "3"))  # display back this long: resume
HDMI_POLL_S = float(os.environ.get("TV7_HDMI_POLL_S", "2"))
hdmi_stopped = {}  # channel stopped by the watcher (pk, name, source, t); empty if none


def hdmi_watch_step(state):
    """One check. Stops playback when no HDMI display is connected for HDMI_OFF_S (option hdmi_disconnect: resume|stop) and,
    with resume, starts the same channel again when the display is back for HDMI_BACK_S. state keeps the timers between calls."""
    mode = settings.current_values().get("hdmi_disconnect", "resume")
    if not display.connectors() or mode == "keep":
        state.clear()
        hdmi_stopped.clear()
        return
    now, ok = time.time(), display.hdmi_ok()
    if state.get("ok") != ok:  # display connected or gone: the web UI shows it
        state["ok"] = ok
        mpvclient.changed()
    if ok:
        state.pop("off_since", None)
        state.setdefault("on_since", now)
    else:
        state.pop("on_since", None)
        state.setdefault("off_since", now)
    if not ok and current["pk"] and not hdmi_stopped and now - state["off_since"] >= HDMI_OFF_S:
        player(_hdmi_stop, mode)
    elif ok and hdmi_stopped and now - state["on_since"] >= HDMI_BACK_S:
        ch = dict(hdmi_stopped)
        hdmi_stopped.clear()
        if mode != "resume":
            return
        try:
            res = start(init7.find_channel(ch["pk"]), ch["source"] if ch["source"] in ("multicast", "hls") else "auto")
            config.log_line(
                f"HDMI display back: {ch['name']} "
                + ("started again" if res["ok"] else "could not be started: " + "; ".join(res["log"]))
            )
        except Exception as e:
            config.log_line(f"HDMI display back: {ch['name']} could not be started: {e}")


def _hdmi_stop(mode):
    if not current["pk"] or hdmi_stopped:
        return
    hdmi_stopped.update(pk=current["pk"], name=current["name"], source=current["source"], t=time.time())
    try:
        mpvclient.mpv("stop")
    except Exception:
        pass
    current.update(pk=None, name=None, source=None)
    config.log_line(
        f"No HDMI display for {HDMI_OFF_S:g} s: playback of {hdmi_stopped['name']} stopped"
        + (", it resumes when the display is back" if mode == "resume" else "")
    )


MINUTE_S = float(os.environ.get("TV7_MINUTE_S", "60"))  # overridable for tests
autostopped = {}  # last automatic stop: {"reason": "idle", "channel", "t", "minutes"}; cleared by the next start
last_activity = {"t": time.time()}


def touch():
    """An operation (start, stop, volume, mute, track): restarts the inactivity time."""
    last_activity["t"] = time.time()


def auto_stop(reason, text, **extra):
    player(_auto_stop, reason, text, extra)


def _auto_stop(reason, text, extra):
    if not current["pk"]:
        return
    autostopped.clear()
    autostopped.update(reason=reason, channel=current["name"], t=time.time(), **extra)
    try:
        mpvclient.mpv("stop")
    except Exception:
        pass
    current.update(pk=None, name=None, source=None)
    hdmi_stopped.clear()
    config.log_line(text)


def autostop_step():
    """No operation for idle_stop minutes while a channel plays: stop, so the app does not load the system when nobody watches."""
    now = time.time()
    idle = settings.current_values().get("idle_stop", "off")
    if idle != "off" and current["pk"] and now - last_activity["t"] >= float(idle) * MINUTE_S:
        auto_stop("idle", f"No operation for {idle} min: playback of {current['name']} stopped", minutes=int(idle))


def watcher():
    """Background checks: HDMI display present, inactivity, TV switched away (HDMI-CEC)."""
    state = {}
    while True:
        for step in (lambda: hdmi_watch_step(state), autostop_step, cec.cec_away_step):
            try:
                step()
            except Exception as e:
                config.log_line(f"Watcher error: {e}")
        time.sleep(HDMI_POLL_S)

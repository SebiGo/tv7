"""What plays: channel start and stop on one worker thread, mpv restarts, the output mode that follows the stream, and
the automatic stops and resumes (HDMI display gone, no operation, TV switched away over HDMI-CEC).

The playback state is `state`. Only this module changes it, and it replaces a field as a whole instead of changing it in
place, so the web UI, the TV menu and the support text, which read it from other threads, always see one consistent
value."""

import concurrent.futures
import itertools
import threading
import time
from dataclasses import dataclass, field

from tv7 import cec, config, display, init7, mpvclient, settings


@dataclass
class Playback:
    # what was started last (shown by /status and the web UI); pk None: nothing plays
    current: dict = field(default_factory=lambda: {"pk": None, "name": None, "source": None})
    # last channel started successfully (pk, source): the play key of the remote starts it again
    last_played: dict = field(default_factory=dict)
    # result and log of the last start someone asked for (support text)
    last_start: dict = field(default_factory=dict)
    # channel stopped by the HDMI watcher (pk, name, source, t); empty if none
    hdmi_stopped: dict = field(default_factory=dict)
    # last automatic stop: reason (idle | cec), channel, t and details; cleared by the next start
    autostopped: dict = field(default_factory=dict)
    # channel stopped because the TV switched away (HDMI-CEC), started again when the TV shows the app
    tv_resume: dict = field(default_factory=dict)
    # the TV switched to another source at this time (None: the TV shows the app)
    tv_away_since: float | None = None
    # last operation (start, stop, volume, mute, track); idle_stop counts from here
    last_activity: float = field(default_factory=time.time)


state = Playback()

# resume(ch, source): starts a channel again after the TV showed another source. control.py sets it to the TV menu's
# start, which shows the channel banner; without it the channel starts in the background.
handlers = {"resume": lambda ch, source: play(ch, source, wait=False)}


def _clear_current():
    state.current = {"pk": None, "name": None, "source": None}


# Every wish that replaces what plays (a start, a stop) takes the next number when it is asked for, before it waits in
# the queue. A start checks the number while it waits for the stream and gives up as soon as a newer wish exists, so a
# stop or another channel never waits behind a start that does not get anywhere.
_wishes = itertools.count(1)
_wish_lock = threading.Lock()
_latest_wish = {"n": 0}


def _new_wish():
    with _wish_lock:
        n = _latest_wish["n"] = next(_wishes)
    return n


def _superseded(n):
    return n is not None and _latest_wish["n"] != n


def stop_playback(wait=True):
    _new_wish()
    return player(_stop_playback, wait=wait)


def _stop_playback():
    _clear_current()
    state.hdmi_stopped = {}
    return mpvclient.mpv("stop")


def restart_mpv(log, reason):
    """Quit mpv; the supervision starts it again (with the current video output and output mode). Waits for the new
    process, restores volume/mute."""
    log.append(f"{reason} (mpv restarts)")
    keep = {"volume": mpvclient.prop("volume"), "mute": mpvclient.prop("mute")}
    old_pid = mpvclient.prop("pid")
    try:
        mpvclient.mpv("quit")
    except Exception:
        pass  # mpv closes the connection when it quits
    end = time.time() + config.MODE_WAIT_S
    while time.time() < end:  # wait for the NEW mpv (different pid) to answer
        time.sleep(0.4)
        pid = mpvclient.prop("pid")
        if pid is not None and pid != old_pid:
            break
    if mpvclient.prop("pid") is None:
        raise RuntimeError("mpv did not come back after the restart")
    for k, v in settings.current_values().items():  # live settings are not in the new mpv's command line
        if k == "audio_channels":
            settings.apply_live(k, v)
    if keep["volume"] is not None:
        mpvclient.mpv("set_property", "volume", keep["volume"])
    if keep["mute"]:
        mpvclient.mpv("set_property", "mute", True)


# Everything that changes what plays (start, stop, automatic stops and resumes, configuration switches) runs on one
# thread, in the order it was asked for, so these actions never overlap. Callers wait for the result or not; code
# holding _menu_lock never waits (the worker takes that lock to update the banner).
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


def play(ch, source="auto", wait=True, done=None):
    """A start someone asked for (web UI, API, TV menu, resume after CEC): clears the notes of automatic stops and keeps
    the result and log for the support text. Returns {"ok", "channel", "source", "log", ...}; "reason": "cancelled"
    when a newer start or a stop came first. wait=False returns at once; done(result) is then called on the worker."""
    n = _new_wish()

    def run():
        res = _play(ch, source, n)
        if done:
            done(res)
        return res

    return player(run, wait=wait)


def _play(ch, source, n=None):
    t0 = time.time()
    state.hdmi_stopped = {}
    state.autostopped = {}
    try:
        res = _start_channel(ch, source, n)
    except Exception as e:
        res = {"ok": False, "channel": ch.get("name"), "log": [f"{type(e).__name__}: {e}"]}
    state.last_start = {"t": t0, "seconds": round(time.time() - t0, 1), "requested": source, **res}
    return res


def start(ch, source):
    """Start a channel without touching the notes of automatic stops (the HDMI watcher resumes with this)."""
    return player(_start_channel, ch, source, _new_wish())


def _start_channel(ch, source, n=None):
    res = _start(ch, source, n)
    if res.get("ok"):
        state.last_played = {"pk": ch["pk"], "source": res.get("source")}
        state.tv_away_since = None
        state.tv_resume = {}
        cec.cec_active_source()  # TV/projector and receiver switch to the app; its remote keys come here
    return res


def _start(ch, source, n=None):
    """Try the sources of a channel (multicast, then HLS), two attempts each. n: the wish this start belongs to (see
    _new_wish); a newer wish ends it."""
    log = []

    def cancelled():
        log.append("cancelled: a newer start or a stop was asked for")
        return {"ok": False, "channel": ch["name"], "log": log, "reason": "cancelled"}

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
            if _superseded(n):
                return cancelled()
            # every channel starts without subtitles (track picker turns them on)
            mpvclient.mpv("set_property", "sid", "no")
            mpvclient.mpv("loadfile", url, "replace")
            end = time.time() + config.START_TIMEOUT
            while time.time() < end:
                if _superseded(n):
                    return cancelled()
                if mpvclient.playing():
                    log.append(f"{src}: started (attempt {attempt})")
                    state.current = {"pk": ch["pk"], "name": ch["name"], "source": src}
                    if match_refresh(log):  # mpv restarted with a new output mode: play the channel again
                        mpvclient.mpv("loadfile", url, "replace")
                        t_end = time.time() + config.START_TIMEOUT
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
                    # The stream runs (time advances) but mpv has no picture output: no display on HDMI. Other attempts
                    # or sources would end the same way.
                    log.append(f"{src}: the stream is received, but no display is connected to HDMI (no picture)")
                    try:
                        mpvclient.mpv("stop")
                    except Exception as e:
                        config.log_once("Stopping mpv", e)
                    return {"ok": False, "channel": ch["name"], "log": log, "reason": "no_display"}
                time.sleep(0.5)
            log.append(f"{src}: attempt {attempt} did not start within {config.START_TIMEOUT:g} s")
    return {"ok": False, "channel": ch["name"], "log": log}


def match_refresh(log):
    """Make the display refresh rate follow the stream's frame rate. Returns True if mpv was restarted."""
    vals = settings.current_values()
    if vals.get("video_mode") == "highest":
        return False
    fps = mpvclient.prop("container-fps") or mpvclient.prop("estimated-vf-fps")
    port = vals.get("hdmi_port") if vals.get("hdmi_port") != "auto" else ""
    modes = display.drm_modes()
    want = display.mode_for_fps(fps, vals.get("video_mode"), port, modes)
    cur = display.current_drm_mode()
    if not cur:  # no override yet: the mode mpv was started with
        cur = display.video_state()["mode"]
    if not cur:  # not known (mpv started by someone else): compute it the same way
        start = {k: settings.applied_value(k) for k in ("video_mode", "hdmi_port")}
        port0 = start["hdmi_port"] if start["hdmi_port"] != "auto" else ""
        cur = display.resolve_mode(start["video_mode"], port0, modes)[0]
    if cur == "preferred":  # find the index of the display's preferred mode
        lists = [modes[port]] if port and port in modes else list(modes.values())
        cur = next((str(m["index"]) for lst in lists for m in lst if m["preferred"]), "")
    if want is None or str(want) == cur:
        return False
    display.set_mode_override(want)
    restart_mpv(log, f"output refresh rate follows the stream ({fps:g} fps)")
    return True


def hdmi_watch_step(timers):
    """One check. Stops playback when no HDMI display is connected for config.HDMI_OFF_S and starts the same channel
    again when the display is back for config.HDMI_BACK_S. timers keeps the times between calls."""
    if not display.connectors():
        timers.clear()
        state.hdmi_stopped = {}
        return
    now, ok = time.time(), display.hdmi_ok()
    if timers.get("ok") != ok:  # display connected or gone: the web UI shows it
        timers["ok"] = ok
        mpvclient.changed()
    if ok:
        timers.pop("off_since", None)
        timers.setdefault("on_since", now)
    else:
        timers.pop("on_since", None)
        timers.setdefault("off_since", now)
    if not ok and state.current["pk"] and not state.hdmi_stopped and now - timers["off_since"] >= config.HDMI_OFF_S:
        player(_hdmi_stop)
    elif ok and state.hdmi_stopped and now - timers["on_since"] >= config.HDMI_BACK_S:
        ch = dict(state.hdmi_stopped)
        state.hdmi_stopped = {}
        try:
            res = start(init7.find_channel(ch["pk"]), ch["source"] if ch["source"] in ("multicast", "hls") else "auto")
            config.log_line(
                f"HDMI display back: {ch['name']} "
                + ("started again" if res["ok"] else "could not be started: " + "; ".join(res["log"]))
            )
        except Exception as e:
            config.log_line(f"HDMI display back: {ch['name']} could not be started: {e}")


def _hdmi_stop():
    if not state.current["pk"] or state.hdmi_stopped:
        return
    cur = state.current
    state.hdmi_stopped = {"pk": cur["pk"], "name": cur["name"], "source": cur["source"], "t": time.time()}
    try:
        mpvclient.mpv("stop")
    except Exception as e:
        config.log_once("Stopping mpv", e)
    _clear_current()
    config.log_line(
        f"No HDMI display for {config.HDMI_OFF_S:g} s: playback of {state.hdmi_stopped['name']} stopped, "
        "it resumes when the display is back"
    )


def touch():
    """An operation (start, stop, volume, mute, track): restarts the inactivity time."""
    state.last_activity = time.time()


def auto_stop(reason, text, **extra):
    player(_auto_stop, reason, text, extra)


def _auto_stop(reason, text, extra):
    if not state.current["pk"]:
        return
    state.autostopped = {"reason": reason, "channel": state.current["name"], "t": time.time(), **extra}
    try:
        mpvclient.mpv("stop")
    except Exception as e:
        config.log_once("Stopping mpv", e)
    _clear_current()
    state.hdmi_stopped = {}
    config.log_line(text)


def autostop_step():
    """No operation for idle_stop minutes while a channel plays: stop, so the app does not load the system when nobody
    watches."""
    idle = settings.current_values().get("idle_stop", "off")
    if idle != "off" and state.current["pk"] and time.time() - state.last_activity >= float(idle) * config.MINUTE_S:
        name = state.current["name"]
        auto_stop("idle", f"No operation for {idle} min: playback of {name} stopped", minutes=int(idle))


def tv_standby():
    """HDMI-CEC: the TV switched to standby."""
    tv_gone("the TV switched to standby")


def tv_gone(reason):
    """The TV switched to standby (at once) or to another source (after config.CEC_AWAY_S): stop like for a missing
    display, and start the same channel again when the TV shows the app again."""
    player(_tv_gone, reason)


def _tv_gone(reason):
    if not state.current["pk"]:
        return
    state.tv_resume = {"pk": state.current["pk"], "source": state.current["source"]}
    state.tv_away_since = None
    auto_stop(
        "cec",
        f"HDMI-CEC: {reason}: playback of {state.current['name']} stopped, it resumes when the TV shows TV7 again",
    )


def tv_shown(ours):
    """HDMI-CEC: the TV switched to a source; ours: to the app."""
    if ours:
        state.tv_away_since = None
        if state.tv_resume and not state.current["pk"]:
            ch = dict(state.tv_resume)
            state.tv_resume = {}
            try:
                config.log_line("HDMI-CEC: the TV shows TV7 again, playback resumes")
                source = ch["source"] if ch["source"] in ("multicast", "hls") else "auto"
                handlers["resume"](init7.find_channel(ch["pk"]), source)
            except Exception as e:
                config.log_line(f"HDMI-CEC: resume failed: {e}")
    elif state.current["pk"] and state.tv_away_since is None:
        state.tv_away_since = time.time()


def tv_away_step():
    """Called by the watcher: the TV has shown another source for config.CEC_AWAY_S."""
    if state.tv_away_since is not None and time.time() - state.tv_away_since >= config.CEC_AWAY_S:
        tv_gone("the TV shows another source")


def watcher():
    """Background checks: HDMI display present, inactivity, TV switched away (HDMI-CEC)."""
    timers = {}
    while True:
        for step in (lambda: hdmi_watch_step(timers), autostop_step, tv_away_step):
            try:
                step()
            except Exception as e:
                config.log_line(f"Watcher error: {e}")
        time.sleep(config.HDMI_POLL_S)

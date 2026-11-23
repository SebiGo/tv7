# Development

Open the folder in VS Code and run **Dev Containers: Reopen in Container**. Two configurations are offered:

| Configuration | For | Needs |
|---|---|---|
| **TV7 Player (web)** | web UI, HTTP API, tests, shell scripts | Docker only |
| **TV7 Player (hardware)** | real HDMI and audio output | Linux host with `/dev/dri`, `/dev/snd`; ideally the Pi itself (VS Code Remote-SSH to the Pi, then reopen in the container) |

## Web server (no hardware)
```
dev/run-web.sh                       # web UI + API against a fake mpv: http://localhost:8099 (forwarded), live reload
python3 tv7_player/tests/test_control.py    # full test suite with mock mpv, fake HDMI and fake channel list (offline)
python3 tv7_player/tests/test_player.py      # starting mpv: decoder per device, audio device, restarts (also run by test_control.py)
yamllint -c .yamllint tv7_player .github repository.yaml   # YAML lint (Debian package yamllint, in the devcontainer image)
shellcheck tv7_player/rootfs/*.sh dev/*.sh
```
The channel list comes from Init7's public API; "playing" a channel only happens in the fake mpv `tv7_player/tests/mock_mpv.py`, which the tests use as well.

**Live reload:** `dev/run-web.sh` sets `TV7_DEV_RELOAD=1`. The version in `/status` then carries the modification time of `ui.html`, the logo, the translations, the texts and the program (`control.py`, `tv7/*.py`), and the open page reloads itself within about 2.5 s after a change (the same mechanism that reloads the page after an app update). When `control.py`, `tv7_player/tests/mock_mpv.py` or a text file in `i18n/` changes, the script restarts both. Only one instance can run (ports 8099 and 8765); stop an old one with Ctrl+C first.

## Video output: what is possible
- The output goes straight to the **DRM/KMS** display (no X11/Wayland). That needs the display exclusively, so it cannot run on a desktop that is showing a graphical session. On a desktop PC: switch to a text console (Ctrl+Alt+F3) and run `/run.sh` in the hardware container, or use a separate GPU/connector (`hdmi_port`).
- Windows/macOS Docker Desktop and WSL2: **no** DRM access; use the web configuration only.
- The Raspberry-specific parts (H.265 hardware decoder, overlay planes, `drm-device` selection) only work on a real Raspberry Pi. On a PC the app falls back to software decoding and the GPU/DRM output of the PC's driver; sound goes through ALSA.
- Practical workflow: develop in the web container, then test the real output on the Pi (copy `tv7_player` to `/local_apps` on Home Assistant OS and update the app, or the hardware devcontainer over Remote-SSH on a Pi).

## Layout
- `tv7_player/rootfs/control.py` the start (production: starts and supervises mpv; with `<socket> <port>` it attaches to an mpv started by someone else: tests, `dev/run-web.sh`). The code is in the package `tv7_player/rootfs/tv7/`: `config` (version, paths, texts), `init7` (channel lists, Init7-only stream addresses, logos, favorites), `mpvclient` (mpv IPC, log, change notifications), `display` (HDMI, modes, planes, decoder choice, output mode), `mpvhost` (starting and supervising mpv), `player` (channel start/stop on one worker thread, HDMI watcher, stop without operation), `tvosd` (technical info, menu, banner, remote keys), `cec` (HDMI-CEC), `settings` (options via the Supervisor), `system` (load, audio devices, nerd data), `support` (support text), `web` (API, web UI, `/events`).
- `tv7_player/rootfs/ui.html` the page; `tv7_player/rootfs/i18n/<lang>.json` its texts ("ui") and those of the TV menu, banner and technical info ("tv"), de/en/fr/it; `tv7_player/translations/<lang>.yaml` the option names and descriptions (Home Assistant's format, also used by the web UI).
- `tv7_player/rootfs/run.sh` only starts `control.py`.
- `tv7_player/` is the Home Assistant app (`config.yaml`, `Dockerfile`, DOCS, translations); `repository.yaml` makes the folder an add-on repository.
- Code, comments and log messages are English; only UI text is translated.

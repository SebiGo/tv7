#!/bin/bash
# TV7 Player: control.py starts and supervises mpv (video output, decoding, output mode, audio device) and serves the web UI
# (Home Assistant Ingress) and the control API for Home Assistant.
exec python3 -B /control.py     # -B: no bytecode cache files next to the code (read-only for the app)

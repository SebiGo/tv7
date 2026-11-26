"""The modules of tv7/ import only modules of lower layers (docs/DEVELOPMENT.md, "Modules and layers"). Upward calls go
through the hooks control.py sets (cec.handlers, player.handlers, mpvclient.on_idle)."""

import ast
import glob
import os

from fakes import ROOTFS

LAYERS = [
    {"config", "png", "hwdec"},  # paths, version, texts, log; PNG decoder; decoder choice per device
    {"init7", "supervisor", "mpvclient"},  # outside services: Init7, the Supervisor, mpv
    {"display", "cec"},  # devices: HDMI/DRM, HDMI-CEC
    {"settings"},  # options
    {"player", "mpvhost"},  # what plays, running mpv
    {"system", "tvdraw"},  # live data for the views; drawing on the TV
    {"tvinfo"},  # technical info on the TV
    {"tvmenu", "support"},  # TV menu, banner and remote keys; support text
    {"web"},  # HTTP API and web UI
]
LAYER = {m: i for i, layer in enumerate(LAYERS) for m in layer}


def tv7_imports(path):
    with open(path) as f:
        tree = ast.parse(f.read())
    return {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "tv7" for a in n.names}


def test_every_module_has_a_layer():
    mods = {os.path.basename(p)[:-3] for p in glob.glob(os.path.join(ROOTFS, "tv7", "*.py"))} - {"__init__"}
    assert mods == set(LAYER), f"missing: {mods - set(LAYER)}, gone: {set(LAYER) - mods}"


def test_imports_go_down_only():
    wrong = []
    for mod, layer in LAYER.items():
        for dep in tv7_imports(os.path.join(ROOTFS, "tv7", f"{mod}.py")):
            if LAYER.get(dep, 99) >= layer:
                wrong.append(f"{mod} (layer {layer}) imports {dep} (layer {LAYER.get(dep)})")
    assert not wrong, wrong

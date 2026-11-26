"""The app's files agree with each other: options in config.yaml, the settings of the web UI and TV menu, the four
translations of the options and the texts of the web UI and TV."""

import json
import os

import yaml

from fakes import APP_DIR, ROOTFS
from tv7 import settings

LANGS = ("en", "de", "fr", "it")


def test_settings_match_config_yaml():
    with open(os.path.join(APP_DIR, "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    opts, schema = cfg["options"], cfg["schema"]
    for s in settings.SETTINGS:
        k = s["key"]
        assert k in opts and str(opts[k]) == str(settings.DEFAULTS.get(k)), f"default of {k}"
        if s["type"] == "choice":
            assert str(schema.get(k)) == "list(" + "|".join(s["choices"]) + ")", f"choices of {k}"
    for lg in LANGS:
        with open(os.path.join(APP_DIR, "translations", f"{lg}.yaml")) as f:
            names = yaml.safe_load(f)["configuration"]
        assert set(opts) == set(names), f"translations/{lg}.yaml: {set(opts) ^ set(names)}"


def test_every_language_has_every_text():
    texts = {}
    for lg in LANGS:
        with open(os.path.join(ROOTFS, "i18n", f"{lg}.json"), encoding="utf-8") as f:
            texts[lg] = json.load(f)
    for lg in LANGS:
        for part in ("ui", "tv"):
            assert set(texts[lg][part]) == set(texts["en"][part]), (
                f"{lg} {part}: {set(texts[lg][part]) ^ set(texts['en'][part])}"
            )

"""Tiny JSON settings file in the platform's usual place."""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {"voice": "", "rate": 180, "hotkeys": False, "font_size": 15}


def config_path() -> str:
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support/OutLoud")
    elif sys.platform == "win32":
        base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "OutLoud")
    else:
        base = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "outloud")
    return os.path.join(base, "config.json")


def load() -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    try:
        with open(config_path(), encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return cfg


def save(cfg: Dict[str, Any]) -> None:
    path = config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    except OSError:
        pass

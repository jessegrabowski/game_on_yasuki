import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app import DEFAULT_DSN

# Global debug flag
DEBUG_MODE: bool = False


@dataclass(frozen=True)
class Hotkeys:
    bow: str = "b"
    flip: str = "f"
    invert: str = "d"
    fill: str = "l"
    destroy: str = "c"

    # Deck actions
    draw: str = "r"
    shuffle: str = "s"
    inspect: str = "i"


DEFAULT_HOTKEYS = Hotkeys()


def _resolve_config_path(config_path: str | Path | None) -> Path:
    return Path(config_path) if config_path else Path.cwd() / "config.yaml"


def _load_config_data(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_hotkeys(config_path: str | Path | None = None) -> Hotkeys:
    data = _load_config_data(_resolve_config_path(config_path))

    gui_cfg = data.get("gui", {}) if isinstance(data, dict) else {}
    keys = gui_cfg.get("hotkeys", {}) if isinstance(gui_cfg, dict) else {}

    def _get(name: str, default: str) -> str:
        val = str(keys.get(name, default)).strip()
        return val or default

    return Hotkeys(
        bow=_get("bow", DEFAULT_HOTKEYS.bow),
        flip=_get("flip", DEFAULT_HOTKEYS.flip),
        invert=_get("invert", DEFAULT_HOTKEYS.invert),
        fill=_get("fill", DEFAULT_HOTKEYS.fill),
        destroy=_get("destroy", DEFAULT_HOTKEYS.destroy),
        draw=_get("draw", DEFAULT_HOTKEYS.draw),
        shuffle=_get("shuffle", DEFAULT_HOTKEYS.shuffle),
        inspect=_get("inspect", DEFAULT_HOTKEYS.inspect),
    )


def load_database_dsn(config_path: str | Path | None = None) -> str:
    env_dsn = os.getenv("L5R_DATABASE_URL")
    if env_dsn:
        env_dsn = env_dsn.strip()
        if env_dsn:
            return env_dsn

    data = _load_config_data(_resolve_config_path(config_path))
    db_cfg = data.get("database", {}) if isinstance(data, dict) else {}
    cfg_dsn = ""
    if isinstance(db_cfg, dict):
        cfg_dsn = str(db_cfg.get("dsn", "")).strip()
    return cfg_dsn or DEFAULT_DSN

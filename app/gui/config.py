from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

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


def load_hotkeys(config_path: str | Path | None = None) -> Hotkeys:
    path = Path(config_path) if config_path else Path.cwd() / "config.yaml"
    if not path.exists():
        return DEFAULT_HOTKEYS
    try:
        data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return DEFAULT_HOTKEYS

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

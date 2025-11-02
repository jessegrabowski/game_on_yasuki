from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Hotkeys:
    bow: str = "b"
    flip: str = "f"
    invert: str = "d"
    fill: str = "l"
    destroy: str = "c"


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

    bow = str(keys.get("bow", DEFAULT_HOTKEYS.bow)).strip() or DEFAULT_HOTKEYS.bow
    flip = str(keys.get("flip", DEFAULT_HOTKEYS.flip)).strip() or DEFAULT_HOTKEYS.flip
    invert = str(keys.get("invert", DEFAULT_HOTKEYS.invert)).strip() or DEFAULT_HOTKEYS.invert
    fill = str(keys.get("fill", DEFAULT_HOTKEYS.fill)).strip() or DEFAULT_HOTKEYS.fill
    destroy = str(keys.get("destroy", DEFAULT_HOTKEYS.destroy)).strip() or DEFAULT_HOTKEYS.destroy

    return Hotkeys(bow=bow, flip=flip, invert=invert, fill=fill, destroy=destroy)

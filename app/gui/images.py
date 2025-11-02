from __future__ import annotations

from pathlib import Path
from typing import Any
import tkinter as tk

from PIL import Image, ImageTk

from app.assets.paths import FATE_BACK, DYNASTY_BACK
from app.game_pieces.constants import Side
from app.gui.constants import CARD_W, CARD_H
from functools import lru_cache


@lru_cache
def load_image(path: Path | str | None, bowed: bool, master: tk.Misc | None = None) -> Any | None:
    if Image is None or ImageTk is None or not path:
        return None
    path_str = str(path)
    try:
        img = Image.open(path_str)
        target = (CARD_W, CARD_H)
        if bowed:
            target = (CARD_H, CARD_W)
            img = img.rotate(90, expand=True)
        resample = getattr(Image, "LANCZOS", None)
        img = img.resize(target) if resample is None else img.resize(target, resample)
        photo = ImageTk.PhotoImage(img, master=master)
        return photo
    except OSError:
        return None


essential_backs = {Side.FATE: FATE_BACK, Side.DYNASTY: DYNASTY_BACK}


def load_back_image(
    side: Side, bowed: bool, image_path: Path | None, master: tk.Misc | None = None
) -> Any | None:
    path = image_path if image_path else essential_backs[side]
    return load_image(path, bowed, master=master)

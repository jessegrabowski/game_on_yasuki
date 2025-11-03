from pathlib import Path
from typing import Any
import tkinter as tk

from PIL import Image, ImageTk

from app.assets.paths import FATE_BACK, DYNASTY_BACK
from app.game_pieces.constants import Side
from app.gui.constants import CARD_W, CARD_H
from functools import lru_cache


@lru_cache(maxsize=1024)
def load_image(
    path: Path | str | None,
    bowed: bool,
    inverted: bool,
    master: tk.Misc | None = None,
) -> Any | None:
    """
    Returns a Tk PhotoImage (master-bound) for the given path.
    Cache key includes the master object identity implicitly via hashing the object.
    """
    if Image is None or ImageTk is None or not path:
        return None
    path_str = str(path)
    try:
        img = Image.open(path_str)
        target = (CARD_W, CARD_H)
        if bowed:
            target = (CARD_H, CARD_W)
            img = img.rotate(-90, expand=True)
        if inverted:
            img = img.rotate(180, expand=True)
        resample = getattr(Image, "LANCZOS", None)
        img = img.resize(target) if resample is None else img.resize(target, resample)

        # PhotoImage is associated with the given master; callers should pass a stable master.
        photo = ImageTk.PhotoImage(img, master=master)
        return photo
    except OSError:
        return None


essential_backs = {Side.FATE: FATE_BACK, Side.DYNASTY: DYNASTY_BACK}


def load_back_image(
    side: Side,
    bowed: bool,
    inverted: bool,
    image_path: Path | None,
    master: tk.Misc | None = None,
) -> Any | None:
    """
    Returns a PhotoImage for the back of a card (custom image if present, else essential back).
    """
    path = image_path if image_path else essential_backs[side]
    return load_image(path, bowed, inverted, master=master)


def clear_image_cache() -> None:
    """Clear all cached PhotoImages (use when changing masters/themes or freeing memory)."""
    load_image.cache_clear()  # type: ignore[attr-defined]


class ImageProvider:
    """
    Small helper that pins a Tk master so callers don't have to. Also gives semantic
    methods for front/back that mirror how sprites think about images.
    """

    def __init__(self, master: tk.Misc):
        self.master = master

    def front(self, image_front: Path | str | None, bowed: bool, inverted: bool) -> Any | None:
        return load_image(image_front, bowed, inverted, master=self.master)

    def back(
        self,
        side: Side,
        bowed: bool,
        inverted: bool,
        image_back: Path | None,
    ) -> Any | None:
        return load_back_image(side, bowed, inverted, image_back, master=self.master)

    def clear(self) -> None:
        # Clears module-level caches (shared across providers).
        clear_image_cache()

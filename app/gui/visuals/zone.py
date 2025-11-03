import tkinter as tk
from app.engine.zones import Zone, ProvinceZone
from app.game_pieces.constants import Side
from app.gui.ui.images import ImageProvider, load_image as _li, load_back_image as _lbi
from app.gui.constants import CARD_W, CARD_H
from app.gui.visuals.visual import Visual


class ZoneVisual(Visual):
    def __init__(
        self,
        zone: Zone,
        x: int,
        y: int,
        w: int,
        h: int,
        tag: str,
        images: ImageProvider | None = None,
    ):
        self.zone = zone
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.tag = tag
        self.images = images

    @property
    def size(self) -> tuple[int, int]:
        return self.w, self.h

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        w, h = self.size
        return (self.x - w // 2, self.y - h // 2, self.x + w // 2, self.y + h // 2)

    def draw(self, canvas: tk.Canvas) -> None:
        x, y = self.x, self.y
        w, h = self.size
        zone = self.zone
        top = zone.cards[-1] if zone.cards else None
        if top is not None:
            bowed = top.bowed
            inverted = top.inverted
            # Province cards should never display bowed
            if isinstance(zone, ProvinceZone):
                bowed = False
                inverted = False
            face_up = top.face_up
            if self.images is not None:
                photo = (
                    self.images.front(top.image_front, bowed, inverted)
                    if face_up
                    else self.images.back(top.side, bowed, inverted, top.image_back)
                )
            else:
                # Fallback for safety: use module loaders
                photo = (
                    _li(top.image_front, bowed, inverted, master=canvas)
                    if face_up
                    else _lbi(top.side, bowed, inverted, top.image_back, master=canvas)
                )
            if photo is not None:
                canvas.create_image(x, y, image=photo, tags=(self.tag, "zone"))
                outline = "#007acc" if top.side is Side.FATE else "#b58900"
                canvas.create_rectangle(
                    x - CARD_W // 2,
                    y - CARD_H // 2,
                    x + CARD_W // 2,
                    y + CARD_H // 2,
                    outline=outline,
                    width=2,
                    tags=(self.tag, "zone"),
                )
                canvas.create_text(
                    x,
                    y,
                    text=f"{zone.name}\n{len(zone)} cards",
                    fill="#eaeaea",
                    tags=(self.tag, "zone"),
                )
                return
        # Fallback (empty or no image)
        outline = "#888"
        if top is None and zone.allowed_side is not None:
            outline = "#007acc" if zone.allowed_side is Side.FATE else "#b58900"
        canvas.create_rectangle(
            x - w // 2,
            y - h // 2,
            x + w // 2,
            y + h // 2,
            outline=outline,
            width=2,
            dash=(4, 2),
            tags=(self.tag, "zone"),
        )
        canvas.create_text(
            x, y, text=f"{zone.name}\n{len(zone)} cards", fill="#cccccc", tags=(self.tag, "zone")
        )

import tkinter as tk
from yasuki_gui import theme
from yasuki_gui.ui.images import ImageProvider, load_image as _li, load_back_image as _lbi
from yasuki_gui.visuals.cardface import RenderCard
from yasuki_gui.visuals.visual import Visual, draw_count_pill


class ZoneVisual(Visual):
    def __init__(
        self,
        cards: list[RenderCard],
        is_province: bool,
        name: str,
        x: int,
        y: int,
        w: int,
        h: int,
        tag: str,
        images: ImageProvider | None = None,
    ):
        self.cards = cards
        self.is_province = is_province
        self.name = name
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
        is_province = self.is_province
        x0, y0, x1, y1 = x - w // 2, y - h // 2, x + w // 2, y + h // 2
        top = self.cards[-1] if self.cards else None
        if top is not None:
            # Province cards always sit upright; a pile's top shows however it was placed.
            bowed = False if is_province else top.bowed
            inverted = False if is_province else top.inverted
            face_up = top.face_up
            if self.images is not None:
                photo = (
                    self.images.front(top.active_face.image_front, bowed, inverted)
                    if face_up
                    else self.images.back(top.side, bowed, inverted, top.image_back)
                )
            else:
                photo = (
                    _li(top.active_face.image_front, bowed, inverted, master=canvas)
                    if face_up
                    else _lbi(top.side, bowed, inverted, top.image_back, master=canvas)
                )
            if photo is not None:
                canvas.create_image(x, y, image=photo, tags=(self.tag, "zone"))
            else:
                canvas.create_rectangle(
                    x0,
                    y0,
                    x1,
                    y1,
                    fill=theme.CARD_FACE if face_up else theme.CARD_BACK,
                    outline="",
                    tags=(self.tag, "zone"),
                )
                if face_up:
                    canvas.create_text(
                        x,
                        y,
                        text=top.active_face.name,
                        fill=theme.INK,
                        font=theme.serif(9, "bold"),
                        width=w - 10,
                        justify="center",
                        tags=(self.tag, "zone"),
                    )
            canvas.create_rectangle(
                x0, y0, x1, y1, outline=theme.CARD_BORDER, width=1, tags=(self.tag, "zone")
            )
            if not is_province and len(self.cards) > 1:
                draw_count_pill(canvas, x1, y1, len(self.cards), self.tag)
            return
        # Empty: a dashed parchment slot for a province, a solid one for a pile, with a faint label.
        canvas.create_rectangle(
            x0,
            y0,
            x1,
            y1,
            fill=theme.LINE_SOFT if is_province else theme.SURFACE,
            outline=theme.LINE,
            width=1,
            dash=(4, 2) if is_province else (),
            tags=(self.tag, "zone"),
        )
        canvas.create_text(
            x,
            y,
            text=self.name,
            fill=theme.INK_DIM,
            font=theme.serif(8),
            width=w - 8,
            justify="center",
            tags=(self.tag, "zone"),
        )

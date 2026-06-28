import tkinter as tk

from yasuki_core.engine.players import PlayerId
from yasuki_gui import theme
from yasuki_gui.constants import CARD_W, CARD_H, HAND_GAP, HAND_PADDING
from yasuki_gui.ui.images import ImageProvider, load_image as _li, load_back_image as _lbi
from yasuki_gui.visuals.cardface import RenderCard
from yasuki_gui.visuals.visual import Visual


class HandVisual(Visual):
    def __init__(
        self,
        cards: list[RenderCard],
        owner: PlayerId | None,
        x: int,
        y: int,
        w: int,
        h: int,
        tag: str,
        images: ImageProvider | None = None,
    ):
        self.cards = cards
        self.owner = owner
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
        return self.x - w // 2, self.y - h // 2, self.x + w // 2, self.y + h // 2

    def _start_x(self) -> int:
        # Center-justify cards within the inner padded width when possible; otherwise left-align.
        n = len(self.cards)
        inner_left = self.x - self.w // 2 + HAND_PADDING
        inner_right = self.x + self.w // 2 - HAND_PADDING
        inner_width = max(0, inner_right - inner_left)
        if n <= 0 or inner_width <= 0:
            return inner_left + CARD_W // 2
        step = self._step()
        # Total content width for n cards laid side-by-side with gaps
        content_width = CARD_W + (n - 1) * step
        base_first_center = inner_left + CARD_W // 2
        if content_width >= inner_width:
            # Not enough space to center; left align at inner-left
            return base_first_center
        # Center content horizontally within inner bounds
        free_space = inner_width - content_width
        desired_first_center = inner_left + (free_space // 2) + CARD_W // 2
        # Clamp so the last card also stays within inner bounds
        max_first_center = inner_right - CARD_W // 2 - (n - 1) * step
        return max(base_first_center, min(desired_first_center, max_first_center))

    def _step(self) -> int:
        return CARD_W + HAND_GAP

    def center_for_index(self, idx: int) -> tuple[int, int]:
        return (self._start_x() + idx * self._step(), self.y)

    def index_at(self, x: int) -> int | None:
        if not self.cards:
            return None
        x0 = self._start_x()
        step = self._step()
        # compute nearest index by division
        rel = x - x0
        idx = round(rel / step)
        if idx < 0 or idx >= len(self.cards):
            return None
        # Also ensure the x is not too far from the index center: allow half step
        center_x = x0 + idx * step
        if abs(x - center_x) > step // 2:
            return None
        return idx

    def draw(self, canvas: tk.Canvas) -> None:
        x, y = self.x, self.y
        w, h = self.size
        # A faint frame marks the hand strip and its empty drop area.
        canvas.create_rectangle(
            x - w // 2,
            y - h // 2,
            x + w // 2,
            y + h // 2,
            outline=theme.LINE_SOFT,
            width=1,
            tags=(self.tag, "zone", "hand"),
        )
        viewer = getattr(canvas, "local_player", None)
        owner = self.owner
        # An opponent's hand card shows its back unless its owner has shown it.
        for i, card in enumerate(self.cards):
            cx, cy = self.center_for_index(i)
            show_front = not (
                owner is not None and viewer is not None and owner != viewer and not card.shown
            )
            front_art = card.active_face.image_front
            if self.images is not None:
                photo = (
                    self.images.front(front_art, card.bowed, card.inverted)
                    if show_front
                    else self.images.back(card.side, card.bowed, card.inverted, card.image_back)
                )
            else:
                photo = (
                    _li(front_art, card.bowed, card.inverted, master=canvas)
                    if show_front
                    else _lbi(card.side, card.bowed, card.inverted, card.image_back, master=canvas)
                )
            cw, ch = (CARD_H, CARD_W) if card.bowed else (CARD_W, CARD_H)
            if photo is not None:
                canvas.create_image(cx, cy, image=photo, tags=(self.tag, "zone", "hand"))
            else:
                canvas.create_rectangle(
                    cx - cw // 2,
                    cy - ch // 2,
                    cx + cw // 2,
                    cy + ch // 2,
                    fill=theme.CARD_FACE if show_front else theme.CARD_BACK,
                    outline="",
                    tags=(self.tag, "zone", "hand"),
                )
                if show_front:
                    canvas.create_text(
                        cx,
                        cy,
                        text=card.active_face.name,
                        fill=theme.INK,
                        font=theme.serif(9, "bold"),
                        width=cw - 10,
                        justify="center",
                        tags=(self.tag, "zone", "hand"),
                    )
            canvas.create_rectangle(
                cx - cw // 2,
                cy - ch // 2,
                cx + cw // 2,
                cy + ch // 2,
                outline=theme.CARD_BORDER,
                width=1,
                tags=(self.tag, "zone", "hand"),
            )

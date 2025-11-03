from dataclasses import dataclass

from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side
from app.gui.constants import CARD_W, CARD_H, CARD_TAG, ART_TAG, BORDER_TAG, SELECT_TAG, LABEL_TAG
from app.gui.images import load_image, load_back_image, ImageProvider
from app.gui.visuals.visual import Visual
import tkinter as tk


@dataclass
class CardSpriteVisual(Visual):
    card: L5RCard
    x: int
    y: int
    tag: str
    images: ImageProvider | None = None

    @property
    def size(self) -> tuple[int, int]:
        w, h = CARD_W, CARD_H
        return (h, w) if self.card.bowed else (w, h)

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        w, h = self.size
        x0 = self.x - w // 2
        y0 = self.y - h // 2
        x1 = self.x + w // 2
        y1 = self.y + h // 2
        return x0, y0, x1, y1

    def _side_outline(self) -> str:
        return "#007acc" if self.card.side is Side.FATE else "#b58900"

    def _base_border_w(self) -> int:
        return 4 if self.card.inverted else 1

    def _subtag(self, name: str) -> str:
        return f"{self.tag}:{name}"

    def _draw_art(self, canvas: tk.Canvas) -> bool:
        x, y = self.x, self.y
        w, h = self.size
        bowed = self.card.bowed
        face_up = self.card.face_up

        img = None
        if self.images is not None:
            if face_up:
                img = self.images.front(self.card.image_front, bowed)
            else:
                img = self.images.back(self.card.side, bowed, self.card.image_back)
        else:
            # fallback no-cache path
            img = (
                load_image(self.card.image_front, bowed, master=canvas)
                if face_up
                else load_back_image(self.card.side, bowed, self.card.image_back, master=canvas)
            )

        if img is not None:
            canvas.create_image(
                x,
                y,
                image=img,
                tags=(self.tag, CARD_TAG, self._subtag(ART_TAG)),
            )
            return True

        # fallback rectangle + label
        fill = "#fafafa" if face_up else "#6b6b6b"
        canvas.create_rectangle(
            x - w // 2,
            y - h // 2,
            x + w // 2,
            y + h // 2,
            fill=fill,
            outline="",
            tags=(self.tag, CARD_TAG, self._subtag(ART_TAG)),
        )
        canvas.create_text(
            x,
            y,
            text=f"{self.card.name}\n{'Bowed' if bowed else 'Ready'}\n"
            f"{'Face Up' if face_up else 'Face Down'}\n"
            f"{'Inverted' if self.card.inverted else ''}",
            fill="#202020",
            tags=(self.tag, CARD_TAG, self._subtag(LABEL_TAG)),
        )
        return False

    def _draw_border(self, canvas: tk.Canvas) -> None:
        x, y = self.x, self.y
        w, h = self.size
        canvas.create_rectangle(
            x - w // 2,
            y - h // 2,
            x + w // 2,
            y + h // 2,
            outline=self._side_outline(),
            width=self._base_border_w(),
            tags=(self.tag, CARD_TAG, self._subtag(BORDER_TAG)),
        )

    def _draw_selection(self, canvas: tk.Canvas, selected: bool) -> None:
        canvas.delete(self._subtag(SELECT_TAG))
        if not selected:
            return
        x, y = self.x, self.y
        w, h = self.size
        canvas.create_rectangle(
            x - w // 2,
            y - h // 2,
            x + w // 2,
            y + h // 2,
            outline="#66ccff",
            width=2,
            tags=(self.tag, CARD_TAG, self._subtag(SELECT_TAG)),
        )

    def draw(self, canvas: tk.Canvas, selected: bool = False) -> None:
        canvas.delete(self.tag)

        self._draw_art(canvas)
        self._draw_border(canvas)
        self._draw_selection(canvas, selected)

        canvas.tag_raise(self._subtag(SELECT_TAG))

    def update_selection(self, canvas: tk.Canvas, selected: bool) -> None:
        self._draw_selection(canvas, selected)
        canvas.tag_raise(self._subtag(SELECT_TAG))

    def move_to(self, canvas: tk.Canvas, x: int, y: int) -> None:
        dx, dy = x - self.x, y - self.y
        if dx == 0 and dy == 0:
            return
        self.x, self.y = x, y
        # Move layers together; no redraw
        for layer in (ART_TAG, BORDER_TAG, SELECT_TAG, LABEL_TAG):
            canvas.move(self._subtag(layer), dx, dy)
        # Also move top-level tag to keep bbox queries consistent
        canvas.move(self.tag, 0, 0)  # no-op but keeps tag grouping predictable

    def refresh_face_state(self, canvas: tk.Canvas) -> None:
        # Called after flip/bow/invert changes; redraw art+border only
        canvas.delete(self._subtag(ART_TAG))
        canvas.delete(self._subtag(BORDER_TAG))
        canvas.delete(self._subtag(LABEL_TAG))
        self._draw_art(canvas)
        self._draw_border(canvas)
        canvas.tag_raise(self._subtag(SELECT_TAG))

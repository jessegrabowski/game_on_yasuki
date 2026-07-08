from dataclasses import dataclass

from yasuki_gui.visuals.cardface import RenderCard
from yasuki_gui import theme
from yasuki_gui.constants import (
    CARD_W,
    CARD_H,
    CARD_TAG,
    ART_TAG,
    BORDER_TAG,
    SELECT_TAG,
    LABEL_TAG,
    NOTE_TAG,
    COUNTER_TAG,
    COUNTER_BADGE_R,
)
from yasuki_gui.ui.images import load_image, load_back_image, ImageProvider
from yasuki_gui.visuals.visual import Visual
import tkinter as tk


@dataclass
class CardSpriteVisual(Visual):
    card: RenderCard
    x: int
    y: int
    tag: str
    images: ImageProvider | None = None
    # Show the card as bowed before the engine commits it — used to preview a producer being tapped
    # for gold during a payment, so the bow is undoable until the player confirms.
    bowed_preview: bool = False
    # Keep a strong reference to the last PhotoImage used when drawing art
    _last_image: object | None = None

    @property
    def _bowed(self) -> bool:
        return self.card.bowed or self.bowed_preview

    @property
    def size(self) -> tuple[int, int]:
        w, h = CARD_W, CARD_H
        return (h, w) if self._bowed else (w, h)

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        w, h = self.size
        x0 = self.x - w // 2
        y0 = self.y - h // 2
        x1 = self.x + w // 2
        y1 = self.y + h // 2
        return x0, y0, x1, y1

    def _side_outline(self) -> str:
        return theme.CARD_BORDER

    def _base_border_w(self) -> int:
        return 1

    def _subtag(self, name: str) -> str:
        return f"{self.tag}:{name}"

    def _draw_art(self, canvas: tk.Canvas) -> bool:
        x, y = self.x, self.y
        w, h = self.size
        bowed = self._bowed
        inverted = self.card.inverted
        face_up = self.card.face_up

        # The presented art is the active face: a double-faced card flipped to its back shows that
        # back's front art, while a single-faced card is its own active face.
        front_art = self.card.active_face.image_front
        img = None
        if self.images is not None:
            if face_up:
                img = self.images.front(front_art, bowed, inverted)
            else:
                img = self.images.back(self.card.side, bowed, inverted, self.card.image_back)
        else:
            # fallback no-cache path
            img = (
                load_image(front_art, bowed, inverted, master=canvas)
                if face_up
                else load_back_image(
                    self.card.side, bowed, inverted, self.card.image_back, master=canvas
                )
            )

        if img is not None:
            # retain reference to prevent Tk image GC
            self._last_image = img
            canvas.create_image(
                x,
                y,
                image=img,
                tags=(self.tag, CARD_TAG, self._subtag(ART_TAG)),
            )
            return True

        # No art on hand: a cream face titled with the card name, or a plain brown back when down.
        self._last_image = None
        fill = theme.CARD_FACE if face_up else theme.CARD_BACK
        canvas.create_rectangle(
            x - w // 2,
            y - h // 2,
            x + w // 2,
            y + h // 2,
            fill=fill,
            outline="",
            tags=(self.tag, CARD_TAG, self._subtag(ART_TAG)),
        )
        if face_up:
            canvas.create_text(
                x,
                y,
                text=self.card.active_face.name,
                fill=theme.INK,
                font=theme.serif(10, "bold"),
                width=w - 10,
                justify="center",
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

    def _draw_note(self, canvas: tk.Canvas) -> None:
        # A bold note over the bottom half of a face-up card, the first thing read while the art
        # above stays visible.
        if not (self.card.note and self.card.face_up):
            return
        x, y = self.x, self.y
        w, h = self.size
        strip_top = y  # the card centre, so the strip covers the bottom half
        bottom = y + h // 2
        canvas.create_rectangle(
            x - w // 2,
            strip_top,
            x + w // 2,
            bottom,
            fill=theme.NOTE_BG,
            outline="",
            tags=(self.tag, CARD_TAG, self._subtag(NOTE_TAG)),
        )
        canvas.create_text(
            x,
            (strip_top + bottom) // 2,
            text=self.card.note,
            fill=theme.NOTE_FG,
            font=theme.serif(10, "bold"),
            width=w - 6,
            justify="center",
            tags=(self.tag, CARD_TAG, self._subtag(NOTE_TAG)),
        )

    def _draw_counters(self, canvas: tk.Canvas) -> None:
        # A gold badge per counter (a wealth token and its siblings) in the top-right corner, with
        # the count inside; badges stack downward when a card carries more than one kind.
        counters = getattr(self.card, "counters", None)
        if not counters:
            return
        w, h = self.size
        cx = self.x + w // 2 - COUNTER_BADGE_R - 2
        cy = self.y - h // 2 + COUNTER_BADGE_R + 2
        for count in counters.values():
            if count <= 0:
                continue
            canvas.create_oval(
                cx - COUNTER_BADGE_R,
                cy - COUNTER_BADGE_R,
                cx + COUNTER_BADGE_R,
                cy + COUNTER_BADGE_R,
                fill=theme.GOLD,
                outline=theme.CARD_BORDER,
                width=1,
                tags=(self.tag, CARD_TAG, self._subtag(COUNTER_TAG)),
            )
            canvas.create_text(
                cx,
                cy,
                text=str(count),
                fill=theme.ON_DARK,
                font=theme.serif(9, "bold"),
                tags=(self.tag, CARD_TAG, self._subtag(COUNTER_TAG)),
            )
            cy += 2 * COUNTER_BADGE_R + 2

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
            outline=theme.SELECT,
            width=2,
            tags=(self.tag, CARD_TAG, self._subtag(SELECT_TAG)),
        )

    def draw(self, canvas: tk.Canvas, selected: bool = False) -> None:
        canvas.delete(self.tag)

        self._draw_art(canvas)
        self._draw_border(canvas)
        self._draw_note(canvas)
        self._draw_counters(canvas)
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
        # Called after flip/bow/invert changes; redraw art+border and keep selection overlay in sync
        # Detect if selection overlay currently exists so we can re-draw it with new geometry
        had_selection = bool(canvas.find_withtag(self._subtag(SELECT_TAG)))
        # Clear layers
        canvas.delete(self._subtag(ART_TAG))
        canvas.delete(self._subtag(BORDER_TAG))
        canvas.delete(self._subtag(LABEL_TAG))
        canvas.delete(self._subtag(NOTE_TAG))
        canvas.delete(self._subtag(COUNTER_TAG))
        canvas.delete(self._subtag(SELECT_TAG))
        # Redraw art and border
        self._draw_art(canvas)
        self._draw_border(canvas)
        self._draw_note(canvas)
        self._draw_counters(canvas)
        # Recreate selection overlay if it was present
        if had_selection:
            self._draw_selection(canvas, True)
        canvas.tag_raise(self._subtag(SELECT_TAG))

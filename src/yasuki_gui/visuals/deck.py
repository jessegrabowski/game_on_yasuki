import tkinter as tk

from yasuki_gui import theme
from yasuki_gui.ui.images import ImageProvider
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.deck import Deck
from yasuki_gui.constants import CARD_W, CARD_H
from yasuki_gui.visuals.visual import Visual, draw_count_pill
from yasuki_core.engine.players import PlayerId


class DeckVisual(Visual):
    def __init__(
        self,
        deck: Deck[L5RCard],
        x: int,
        y: int,
        tag: str,
        label: str = "Deck",
        images: ImageProvider | None = None,
    ):
        self.deck = deck
        self.x = x
        self.y = y
        self.tag = tag
        self.label = label
        self.images = images

        self.owner: PlayerId | None = None

    @property
    def size(self) -> tuple[int, int]:
        return CARD_W, CARD_H

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        w, h = self.size
        return (self.x - w // 2, self.y - h // 2, self.x + w // 2, self.y + h // 2)

    def draw(self, canvas: tk.Canvas) -> None:
        x, y = self.x, self.y
        w, h = self.size
        x0, y0, x1, y1 = x - w // 2, y - h // 2, x + w // 2, y + h // 2
        count = len(self.deck.cards)
        top = self.deck.peek(1)
        photo = None
        if top and self.images is not None:
            top_card = top[0]
            photo = self.images.back(
                top_card.side, bowed=False, inverted=False, image_back=top_card.image_back
            )
        if photo is not None:
            canvas.create_image(x, y, image=photo, tags=(self.tag, "deck"))
        else:
            canvas.create_rectangle(
                x0,
                y0,
                x1,
                y1,
                fill=theme.CARD_BACK if count else theme.SURFACE,
                outline=theme.CARD_BACK_BORDER if count else theme.LINE,
                width=1,
                tags=(self.tag, "deck"),
            )
        label_fill = theme.ON_DARK if count else theme.INK_DIM
        canvas.create_text(
            x,
            y0 + 8,
            text=self.label,
            fill=label_fill,
            font=theme.serif(8),
            tags=(self.tag, "deck"),
        )
        if count:
            draw_count_pill(canvas, x1, y1, count, self.tag)

import tkinter as tk

from app.gui.ui.images import ImageProvider
from app.paths import FATE_BACK, DYNASTY_BACK
from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side
from app.game_pieces.deck import Deck
from app.gui.constants import CARD_W, CARD_H
from app.gui.visuals.visual import Visual
from app.engine.players import PlayerId


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
        top = self.deck.peek(1)
        if top:
            top_card = top[0]
            # Use ImageProvider when available; else minimal fallback by side path
            if self.images is not None:
                photo = self.images.back(
                    top_card.side, bowed=False, inverted=False, image_back=top_card.image_back
                )
            else:
                # Fallback path maintained for compatibility
                path = top_card.image_back or (
                    FATE_BACK if top_card.side is Side.FATE else DYNASTY_BACK
                )
                from app.gui.ui.images import load_image as _li

                photo = _li(path, bowed=False, inverted=False, master=canvas)
            if photo is not None:
                canvas.create_image(x, y, image=photo, tags=(self.tag, "deck"))
                canvas.create_text(
                    x,
                    y,
                    text=f"{self.label}\n{len(self.deck.cards)} cards",
                    fill="#eaeaea",
                    tags=(self.tag, "deck"),
                )
                return
        # Fallback rectangle if no cards or image load failed
        canvas.create_rectangle(
            x - w // 2,
            y - h // 2,
            x + w // 2,
            y + h // 2,
            fill="#3b3b3b",
            outline="#aaaaaa",
            width=2,
            tags=(self.tag, "deck"),
        )
        canvas.create_text(
            x,
            y,
            text=f"{self.label}\n{len(self.deck.cards)} cards",
            fill="#eaeaea",
            tags=(self.tag, "deck"),
        )

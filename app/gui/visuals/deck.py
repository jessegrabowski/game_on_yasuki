import tkinter as tk

from app.gui.images import load_image
from app.assets.paths import FATE_BACK, DYNASTY_BACK
from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side
from app.game_pieces.deck import Deck
from app.gui.constants import CARD_W, CARD_H
from app.gui.visuals.visual import Visual


class DeckVisual(Visual):
    def __init__(self, deck: Deck[L5RCard], x: int, y: int, tag: str, label: str = "Deck"):
        self.deck = deck
        self.x = x
        self.y = y
        self.tag = tag
        self.label = label

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
            back_path = top_card.image_back or (
                FATE_BACK if top_card.side is Side.FATE else DYNASTY_BACK
            )
            photo = load_image(back_path, bowed=False, master=canvas)
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

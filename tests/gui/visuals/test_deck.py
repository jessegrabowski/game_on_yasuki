import tkinter as tk

from app.gui.visuals.deck import DeckVisual
from app.game_pieces.deck import Deck
from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side


def test_size_bbox_and_draw_empty_fallback(root):
    deck = Deck.build([])
    dv = DeckVisual(deck, x=100, y=120, tag="deck:1", label="Test Deck")
    w, h = dv.size
    assert dv.bbox == (100 - w // 2, 120 - h // 2, 100 + w // 2, 120 + h // 2)

    cv = tk.Canvas(root, width=300, height=300)
    cv.pack()
    root.update_idletasks()
    root.update()

    before = len(cv.find_withtag("deck:1"))
    dv.draw(cv)
    after = len(cv.find_withtag("deck:1"))
    assert after >= before + 2  # rect + text


def test_draw_with_top_card_uses_back_image_or_fallback(root):
    c = L5RCard(id="d1", name="C1", side=Side.FATE)
    deck = Deck.build([c])
    dv = DeckVisual(deck, x=60, y=60, tag="deck:2", label="Fate Deck")

    cv = tk.Canvas(root, width=200, height=200)
    cv.pack()
    root.update_idletasks()
    root.update()

    dv.draw(cv)
    items = cv.find_withtag("deck:2")
    assert items  # at least one item drawn

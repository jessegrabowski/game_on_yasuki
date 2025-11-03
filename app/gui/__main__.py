import tkinter as tk

from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side
from app.game_pieces.fate import FateCard
from app.game_pieces.dynasty import DynastyCard
from app.game_pieces.deck import Deck
from app.gui.field_view import GameField
from app.gui.config import load_hotkeys
from app.gui.constants import CARD_W, CARD_H
from app.engine.zones import (
    HandZone,
    ProvinceZone,
    FateDiscardZone,
    DynastyDiscardZone,
    BattlefieldZone,
)


def main() -> None:
    root = tk.Tk()
    root.title("Game on Yasuki - Game Field")

    hotkeys = load_hotkeys()
    W, H = 1200, 800
    field = GameField(root, width=W, height=H)
    field.pack(fill="both", expand=True)
    field.configure_hotkeys(hotkeys)

    # Zones (battlefield tracked but not drawn)
    hand = HandZone()
    fate_discard = FateDiscardZone()
    dynasty_discard = DynastyDiscardZone()
    battlefield = BattlefieldZone()
    field.set_battlefield_zone(battlefield)

    # Layout: hand bottom
    field.add_zone(hand, x=W // 2, y=H - 60, w=W - 200, h=120)

    # Decks: Dynasty left, Fate right
    dynasty_cards = [
        DynastyCard(id=f"d{i}", name=f"Dynasty {i}", side=Side.DYNASTY) for i in range(1, 11)
    ]
    fate_cards = [FateCard(id=f"f{i}", name=f"Fate {i}", side=Side.FATE) for i in range(1, 11)]
    dynasty_deck = Deck.build(dynasty_cards)
    fate_deck = Deck.build(fate_cards)

    field.add_deck(dynasty_deck, x=200, y=H - 200, label="Dynasty Deck")
    field.add_deck(fate_deck, x=W - 200, y=H - 200, label="Fate Deck")

    # Discard zones outside of their decks (one card-sized)
    field.add_zone(dynasty_discard, x=80, y=H - 200, w=CARD_W, h=CARD_H)
    field.add_zone(fate_discard, x=W - 80, y=H - 200, w=CARD_W, h=CARD_H)

    # Province: four separate card-sized zones centered between decks
    y_prov = H - 200
    centers = [
        int(W // 2 - 1.5 * CARD_W),
        int(W // 2 - 0.5 * CARD_W),
        int(W // 2 + 0.5 * CARD_W),
        int(W // 2 + 1.5 * CARD_W),
    ]
    for i, cx in enumerate(centers, start=1):
        field.add_zone(ProvinceZone(name=f"Province {i}"), x=cx, y=y_prov, w=CARD_W, h=CARD_H)

    # Demo cards (tracked in battlefield)
    c1 = L5RCard(id="demo-1", name="Sample Fate", side=Side.FATE)
    c2 = L5RCard(id="demo-2", name="Sample Dynasty", side=Side.DYNASTY)
    field.add_card(c1, x=W // 2 - 100, y=H // 2 - 50)
    field.add_card(c2, x=W // 2 + 100, y=H // 2 - 50)

    tk.Label(
        root,
        text=(
            f"Drag cards to move. Drop onto zones to move them. Double-click a deck to draw toward the center.\n"
            f"Shortcuts: Bow ({hotkeys.bow}), Flip ({hotkeys.flip}), Invert ({hotkeys.invert})."
        ),
        bg="#e0e0e0",
        wraplength=W - 100,
        justify="left",
    ).pack(fill="x")

    root.mainloop()


if __name__ == "__main__":
    main()

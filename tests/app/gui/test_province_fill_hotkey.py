from types import SimpleNamespace

from app.gui.field import GameField
from app.gui.config import Hotkeys
from app.engine.zones import ProvinceZone
from app.game_pieces.deck import Deck
from app.game_pieces.dynasty import DynastyCard
from app.game_pieces.constants import Side


def test_hover_province_press_l_fills_from_dynasty_deck(root, monkeypatch):
    field = GameField(root, width=600, height=400)
    field.pack()
    root.update_idletasks()
    root.update()

    # Province to fill
    prov = ProvinceZone()
    prov_tag = field.add_zone(prov, x=300, y=200, w=120, h=160)

    # Dynasty deck with one card
    cards = [DynastyCard(id="d1", name="D1", side=Side.DYNASTY)]
    deck = Deck.build(cards)
    field.add_deck(deck, x=100, y=100, label="Dynasty Deck")

    # Hover the province
    monkeypatch.setattr(field, "_resolve_tag_at", lambda e: prov_tag)
    field._on_move(SimpleNamespace(x=300, y=200))
    assert field._hover_zone_tag == prov_tag

    # Press the fill hotkey (defaults)
    hk = Hotkeys()
    field._on_key(SimpleNamespace(keysym=hk.fill))

    # Province now has the card, face-down, and deck size reduced
    assert len(prov) == 1
    top = prov.cards[-1]
    assert top.face_up is False
    assert len(deck.cards) == 0

import tkinter as tk
import pytest

from app.gui.field_view import FieldView
from app.gui.services.drag import DragKind
from app.gui.services.actions import FieldActions
from app.game_pieces.deck import Deck
from app.game_pieces.fate import FateCard
from app.game_pieces.dynasty import DynastyCard
from app.engine.zones import HandZone, FateDiscardZone, ProvinceZone
from app.engine.players import PlayerId
from app.game_pieces.constants import Side


@pytest.fixture()
def view(root):
    v = FieldView(root, width=800, height=600)
    v.pack()
    v.local_player = PlayerId.P1
    root.update_idletasks()
    root.update()
    return v


def test_controller_gating_opponent_objects(view, root, monkeypatch):
    # Opponent deck (P2)
    cards = [FateCard(id=f"f{i}", name=f"F{i}", side=Side.FATE) for i in range(2)]
    deck = Deck.build(cards)
    dtag = view.add_deck(deck, x=200, y=200, label="Fate Deck")
    view._decks[dtag].owner = PlayerId.P2
    root.update_idletasks()
    root.update()
    monkeypatch.setattr(view, "resolve_tag_at", lambda e: dtag)
    # Try to start deck drag
    view._controller.on_press(type("E", (), {"x": 200, "y": 200})())
    assert view._controller.drag.kind is DragKind.NONE

    # Opponent hand zone (P2)
    htag = view.add_zone(HandZone(owner=PlayerId.P2), x=300, y=500, w=500, h=80)
    root.update_idletasks()
    root.update()
    monkeypatch.setattr(view, "resolve_tag_at", lambda e: htag)
    view._controller.on_press(type("E", (), {"x": 300, "y": 500})())
    assert view._controller.drag.kind is DragKind.NONE


def test_action_gating_deck_draw_on_opponent_deck_has_no_effect(view):
    cards = [DynastyCard(id=f"d{i}", name=f"D{i}", side=Side.DYNASTY) for i in range(2)]
    deck = Deck.build(cards)
    dtag = view.add_deck(deck, x=250, y=250, label="Dynasty Deck")
    dv = view._decks[dtag]
    dv.owner = PlayerId.P2  # opponent
    fa = FieldActions(view)
    before = len(deck.cards)
    rd = fa.deck_draw(dtag)
    # No redraws expected and deck unchanged
    assert len(rd.decks) == 0 and len(deck.cards) == before


def test_routing_correctness_send_p1_card_to_p2_targets_noop(view):
    # Create a P1 card sprite
    card = FateCard(id="p1f1", name="P1F1", side=Side.FATE)
    object.__setattr__(card, "owner", PlayerId.P1)
    tag = view.add_card(card, x=100, y=100)
    # Create opponent discard zone and deck
    fdisc = FateDiscardZone(owner=PlayerId.P2)
    ztag = view.add_zone(fdisc, x=500, y=200, w=120, h=160)
    deck = Deck.build([FateCard(id="fX", name="FX", side=Side.FATE)])
    dtag = view.add_deck(deck, x=600, y=200, label="Fate Deck")
    view._decks[dtag].owner = PlayerId.P2
    # Attempt sends
    fa = FieldActions(view)
    rd1 = fa.send_to_fate_discard(tag)
    rd2 = fa.send_to_deck_top(tag)
    # Sprite still exists; zone/deck unchanged
    assert tag in view._sprites
    assert len(view._zones[ztag].zone.cards) == 0
    assert len(view._decks[dtag].deck.cards) == 1
    assert len(rd1.zones) == 0 and len(rd2.decks) == 0


def test_drop_correctness_p1_card_onto_p2_zone_and_deck_leaves_sprite(view):
    # P1 dynasty card sprite
    dcard = DynastyCard(id="p1d1", name="P1D1", side=Side.DYNASTY)
    object.__setattr__(dcard, "owner", PlayerId.P1)
    stag = view.add_card(dcard, x=120, y=120)
    # Opponent province zone and dynasty deck
    prov_tag = view.add_zone(ProvinceZone(owner=PlayerId.P2), x=300, y=200, w=120, h=160)
    deck = Deck.build([DynastyCard(id="dX", name="DX", side=Side.DYNASTY)])
    dtag = view.add_deck(deck, x=400, y=200, label="Dynasty Deck")
    view._decks[dtag].owner = PlayerId.P2
    fa = FieldActions(view)
    rd_z = fa.drop_sprite_into_zone(stag, prov_tag)
    rd_d = fa.drop_sprite_into_deck(stag, dtag)
    # Still a sprite; nothing moved
    assert stag in view._sprites
    assert len(view._zones[prov_tag].zone.cards) == 0
    assert len(view._decks[dtag].deck.cards) == 1
    assert len(rd_z.zones) == 0 and len(rd_d.decks) == 0


def test_menu_filtering_opponent_deck_shows_no_enabled_actions(view, root, monkeypatch):
    # Opponent dynasty deck
    deck = Deck.build([DynastyCard(id="d1", name="D1", side=Side.DYNASTY)])
    dtag = view.add_deck(deck, x=220, y=160, label="Dynasty Deck")
    view._decks[dtag].owner = PlayerId.P2
    root.update_idletasks()
    root.update()
    monkeypatch.setattr(tk.Menu, "tk_popup", lambda self, x, y: None)
    monkeypatch.setattr(view, "resolve_tag_at", lambda e: dtag)
    view._controller.on_context(type("E", (), {"x_root": 10, "y_root": 10})())
    menu = view._controller._context_menu
    end = menu.index("end") or -1
    # All entries should be disabled
    for i in range(end + 1):
        state = menu.entrycget(i, "state")
        assert state == "disabled"

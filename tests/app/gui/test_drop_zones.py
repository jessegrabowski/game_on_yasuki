from types import SimpleNamespace

from app.gui.field import GameField
from app.engine.zones import HandZone, FateDiscardZone, ProvinceZone
from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side


def test_drag_drop_into_hand_zone_adds_and_removes_sprite(root, monkeypatch):
    field = GameField(root, width=600, height=400)
    field.pack()
    root.update_idletasks()
    root.update()

    hand = HandZone()
    _ = field.add_zone(hand, x=300, y=350, w=500, h=80)

    card = L5RCard(id="z1", name="Z1", side=Side.FATE)
    tag = field.add_card(card, x=100, y=100)
    root.update_idletasks()
    root.update()

    # Ensure press selects the card in headless tests
    monkeypatch.setattr(field, "_resolve_tag_at", lambda e: tag)

    # Start drag
    field._on_press(SimpleNamespace(x=100, y=100))
    # Move the card near the hand zone
    field._on_motion(SimpleNamespace(x=300, y=330))
    # Release over zone
    field._on_release(SimpleNamespace(x=300, y=330))

    # Sprite removed from canvas and field
    assert tag not in field._sprites
    # Card added to hand zone
    assert len(hand) == 1


def test_drag_drop_into_fate_discard_zone(root, monkeypatch):
    field = GameField(root, width=600, height=400)
    field.pack()
    root.update_idletasks()
    root.update()

    fate_disc = FateDiscardZone()
    _ = field.add_zone(fate_disc, x=500, y=200, w=120, h=160)

    card = L5RCard(id="z2", name="Z2", side=Side.FATE)
    tag = field.add_card(card, x=400, y=100)
    root.update_idletasks()
    root.update()

    monkeypatch.setattr(field, "_resolve_tag_at", lambda e: tag)

    field._on_press(SimpleNamespace(x=400, y=100))
    field._on_motion(SimpleNamespace(x=500, y=200))
    field._on_release(SimpleNamespace(x=500, y=200))

    assert tag not in field._sprites
    assert len(fate_disc) == 1


def test_invalid_drop_fate_into_province_is_ignored(root, monkeypatch):
    field = GameField(root, width=600, height=400)
    field.pack()
    root.update_idletasks()
    root.update()

    prov = ProvinceZone()
    _ = field.add_zone(prov, x=300, y=200, w=200, h=100)

    card = L5RCard(id="pf1", name="PF1", side=Side.FATE)
    tag = field.add_card(card, x=100, y=100)
    root.update_idletasks()
    root.update()

    monkeypatch.setattr(field, "_resolve_tag_at", lambda e: tag)

    field._on_press(SimpleNamespace(x=100, y=100))
    field._on_motion(SimpleNamespace(x=300, y=200))
    field._on_release(SimpleNamespace(x=300, y=200))

    # Sprite remains and province unaffected
    assert tag in field._sprites
    assert len(prov) == 0


def test_invalid_drop_dynasty_into_hand_is_ignored(root, monkeypatch):
    field = GameField(root, width=600, height=400)
    field.pack()
    root.update_idletasks()
    root.update()

    hand = HandZone()
    _ = field.add_zone(hand, x=300, y=350, w=500, h=80)

    card = L5RCard(id="ph1", name="PH1", side=Side.DYNASTY)
    tag = field.add_card(card, x=100, y=100)
    root.update_idletasks()
    root.update()

    monkeypatch.setattr(field, "_resolve_tag_at", lambda e: tag)

    field._on_press(SimpleNamespace(x=100, y=100))
    field._on_motion(SimpleNamespace(x=300, y=350))
    field._on_release(SimpleNamespace(x=300, y=350))

    assert tag in field._sprites
    assert len(hand) == 0


def test_clear_selection_after_drop_does_not_error(root, monkeypatch):
    field = GameField(root, width=600, height=400)
    field.pack()
    root.update_idletasks()
    root.update()

    hand = HandZone()
    field.add_zone(hand, x=300, y=350, w=500, h=80)

    card = L5RCard(id="z3", name="Z3", side=Side.FATE)
    tag = field.add_card(card, x=100, y=100)
    root.update_idletasks()
    root.update()

    # Ensure press selects the card and starts drag
    monkeypatch.setattr(field, "_resolve_tag_at", lambda e: tag)
    field._on_press(SimpleNamespace(x=100, y=100))
    assert tag in field._selected
    # Drag and drop into hand (removes sprite and clears selection entry via removal)
    field._on_motion(SimpleNamespace(x=300, y=350))
    field._on_release(SimpleNamespace(x=300, y=350))

    assert tag not in field._sprites

    # Background click should try to clear selection but not crash
    monkeypatch.setattr(field, "_resolve_tag_at", lambda e: None)
    field._on_press(SimpleNamespace(x=10, y=10))
    assert field._selected == set()

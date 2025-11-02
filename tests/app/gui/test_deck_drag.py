from types import SimpleNamespace

from app.gui.field import GameField
from app.game_pieces.deck import Deck
from app.game_pieces.fate import FateCard
from app.game_pieces.dynasty import DynastyCard
from app.game_pieces.constants import Side


def test_press_on_fate_deck_starts_drag_and_creates_face_down_card(root, monkeypatch):
    field = GameField(root, width=600, height=400)
    field.pack()
    root.update_idletasks()
    root.update()

    cards = [FateCard(id=f"f{i}", name=f"Fate {i}", side=Side.FATE) for i in range(3)]
    deck = Deck.build(cards)
    deck_tag = field.add_deck(deck, x=200, y=200, label="Fate Deck")
    root.update_idletasks()
    root.update()

    start_count = len(deck.cards)
    before_sprites = set(field._sprites.keys())

    # Simulate mousedown on the deck
    monkeypatch.setattr(field, "_resolve_tag_at", lambda e: deck_tag)
    field._on_press(SimpleNamespace(x=200, y=200))
    # Single click should not draw; leaving the deck bounds should initiate draw and drag
    field._on_motion(SimpleNamespace(x=400, y=200))

    assert len(deck.cards) == start_count - 1
    after_sprites = set(field._sprites.keys())
    new_tags = after_sprites - before_sprites
    assert len(new_tags) == 1
    new_tag = next(iter(new_tags))
    sprite = field._sprites[new_tag]
    assert sprite.card.face_up is False
    assert (sprite.x, sprite.y) == (400, 200)


def test_drag_motion_moves_new_card_sprite_after_deck_press(root, monkeypatch):
    field = GameField(root, width=600, height=400)
    field.pack()
    root.update_idletasks()
    root.update()

    cards = [DynastyCard(id=f"d{i}", name=f"Dynasty {i}", side=Side.DYNASTY) for i in range(2)]
    deck = Deck.build(cards)
    deck_tag = field.add_deck(deck, x=250, y=250, label="Dynasty Deck")
    root.update_idletasks()
    root.update()

    before_sprites = set(field._sprites.keys())
    monkeypatch.setattr(field, "_resolve_tag_at", lambda e: deck_tag)
    field._on_press(SimpleNamespace(x=250, y=250))

    # Move outside deck to trigger card creation
    field._on_motion(SimpleNamespace(x=100, y=100))
    new_tag = (set(field._sprites.keys()) - before_sprites).pop()

    # Continue dragging to a new location and release
    field._on_motion(SimpleNamespace(x=300, y=300))
    field._on_release(SimpleNamespace(x=300, y=300))

    sprite = field._sprites[new_tag]
    assert (sprite.x, sprite.y) == (300, 300)

import pytest
from types import SimpleNamespace

from app.gui.field import GameField
from app.gui.config import Hotkeys
from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side
from app.game_pieces.deck import Deck
from app.game_pieces.fate import FateCard
from app.game_pieces.dynasty import DynastyCard
from app.gui.constants import CARD_W, DRAW_OFFSET


@pytest.fixture
def field(root):
    f = GameField(root, width=600, height=400)
    f.pack()
    # ensure canvas is realized before drawing/asserting
    root.update_idletasks()
    root.update()
    # Use defaults (b/f/d)
    f.configure_hotkeys(Hotkeys())
    return f


def test_double_click_card_toggles_bow(field, root, monkeypatch):
    card = L5RCard(id="c1", name="Test", side=Side.FATE)
    tag = field.add_card(card, x=100, y=100)
    root.update_idletasks()
    root.update()

    assert field._sprites[tag].card.bowed is False
    monkeypatch.setattr(field, "_resolve_tag_at", lambda e: tag)

    field._on_double_click(SimpleNamespace(x=100, y=100))
    assert field._sprites[tag].card.bowed is True
    field._on_double_click(SimpleNamespace(x=100, y=100))
    assert field._sprites[tag].card.bowed is False


def test_drag_moves_card(field, root, monkeypatch):
    card = L5RCard(id="c2", name="Drag", side=Side.DYNASTY)
    tag = field.add_card(card, x=100, y=100)
    root.update_idletasks()
    root.update()

    monkeypatch.setattr(field, "_resolve_tag_at", lambda e: tag)
    field._on_press(SimpleNamespace(x=100, y=100))
    field._on_motion(SimpleNamespace(x=150, y=130))
    field._on_release(SimpleNamespace(x=150, y=130))

    sprite = field._sprites[tag]
    assert (sprite.x, sprite.y) == (150, 130)


def test_double_click_deck_draws_face_down(field, root, monkeypatch):
    cards = [FateCard(id=f"f{i}", name=f"Fate {i}", side=Side.FATE) for i in range(3)]
    deck = Deck.build(cards)

    deck_tag = field.add_deck(deck, x=200, y=250, label="Fate Deck")
    root.update_idletasks()
    root.update()

    start_count = len(deck.cards)
    before_tags = set(field._sprites.keys())

    monkeypatch.setattr(field, "_resolve_tag_at", lambda e: deck_tag)
    field._on_double_click(SimpleNamespace(x=200, y=250))

    assert len(deck.cards) == start_count - 1
    after_tags = set(field._sprites.keys())
    new_tags = after_tags - before_tags
    assert len(new_tags) == 1
    new_tag = new_tags.pop()

    sprite = field._sprites[new_tag]
    assert sprite.card.face_up is False
    visual = field._decks[deck_tag]
    assert (sprite.x, sprite.y) == (visual.x - (CARD_W + DRAW_OFFSET), visual.y)


def test_context_menu_labels_and_actions(field, root, monkeypatch):
    hk = Hotkeys(bow="b", flip="f", invert="d")
    field.configure_hotkeys(hk)

    card = L5RCard(id="c3", name="Menu", side=Side.FATE)
    tag = field.add_card(card, x=120, y=120)
    root.update_idletasks()
    root.update()

    field._build_context_menu_for(tag)
    labels = [
        field._context_menu.entrycget(i, "label")
        for i in range(field._context_menu.index("end") + 1)
    ]
    assert labels[:3] == [f"Bow ({hk.bow})", f"Invert ({hk.invert})", f"Flip Down ({hk.flip})"]
    assert labels[-1] == "Send to"

    field._cmd_invert(tag)
    field._build_context_menu_for(tag)
    labels = [
        field._context_menu.entrycget(i, "label")
        for i in range(field._context_menu.index("end") + 1)
    ]
    assert labels[:3] == [f"Bow ({hk.bow})", f"Uninvert ({hk.invert})", f"Flip Down ({hk.flip})"]
    assert labels[-1] == "Send to"

    field._cmd_flip_down(tag)
    field._build_context_menu_for(tag)
    labels = [
        field._context_menu.entrycget(i, "label")
        for i in range(field._context_menu.index("end") + 1)
    ]
    assert labels[:3] == [f"Bow ({hk.bow})", f"Uninvert ({hk.invert})", f"Flip Up ({hk.flip})"]
    assert labels[-1] == "Send to"

    field._cmd_bow(tag)
    field._build_context_menu_for(tag)
    labels = [
        field._context_menu.entrycget(i, "label")
        for i in range(field._context_menu.index("end") + 1)
    ]
    assert labels[:3] == [f"Unbow ({hk.bow})", f"Uninvert ({hk.invert})", f"Flip Up ({hk.flip})"]
    assert labels[-1] == "Send to"

    field._context_tag = tag
    field._build_context_menu_for(tag)
    field._invoke_context_shortcut(hk.bow)
    assert field._sprites[tag].card.bowed is False


def test_keyboard_shortcuts_toggle_hovered_card_with_custom_hotkeys(field, root, monkeypatch):
    # Remap shortcuts and ensure they work
    hk = Hotkeys(bow="x", flip="y", invert="z")
    field.configure_hotkeys(hk)

    c = L5RCard(id="kb1", name="KB", side=Side.FATE)
    tag = field.add_card(c, x=160, y=160)
    root.update_idletasks()
    root.update()

    monkeypatch.setattr(field, "_resolve_tag_at", lambda e: tag)
    field._on_move(SimpleNamespace(x=160, y=160))
    assert field._hover_tag == tag

    field._on_key(SimpleNamespace(keysym=hk.bow))
    assert field._sprites[tag].card.bowed is True
    field._on_key(SimpleNamespace(keysym=hk.bow))
    assert field._sprites[tag].card.bowed is False

    field._on_key(SimpleNamespace(keysym=hk.flip))
    assert field._sprites[tag].card.face_up is False
    field._on_key(SimpleNamespace(keysym=hk.flip))
    assert field._sprites[tag].card.face_up is True

    field._on_key(SimpleNamespace(keysym=hk.invert))
    assert field._sprites[tag].card.inverted is True
    field._on_key(SimpleNamespace(keysym=hk.invert))
    assert field._sprites[tag].card.inverted is False


def test_marquee_selects_multiple_cards_and_hotkeys_apply(field, root, monkeypatch):
    ctags = [
        field.add_card(L5RCard(id="m1", name="M1", side=Side.FATE), x=100, y=100),
        field.add_card(L5RCard(id="m2", name="M2", side=Side.FATE), x=160, y=120),
        field.add_card(L5RCard(id="m3", name="M3", side=Side.DYNASTY), x=260, y=200),
    ]
    root.update_idletasks()
    root.update()

    # Start marquee on background
    field._on_press(SimpleNamespace(x=80, y=80))
    field._on_move(SimpleNamespace(x=190, y=150))
    field._on_release(SimpleNamespace(x=190, y=150))

    # Expect first two selected
    assert set(field._selected) == set(ctags[:2])

    # Press 'b' to bow both
    field._on_key(SimpleNamespace(keysym=Hotkeys().bow))
    assert all(field._sprites[t].card.bowed for t in ctags[:2])

    # Press 'f' to flip both face-down
    field._on_key(SimpleNamespace(keysym=Hotkeys().flip))
    assert all(field._sprites[t].card.face_up is False for t in ctags[:2])

    # Press Escape clears selection
    field._on_escape(SimpleNamespace())
    assert field._selected == set()


def test_background_click_clears_selection(field, root):
    _ = field.add_card(L5RCard(id="s1", name="S1", side=Side.FATE), x=100, y=100)
    root.update_idletasks()
    root.update()

    # Select the card by clicking it
    field._on_press(SimpleNamespace(x=100, y=100))
    # Background click clears
    field._on_press(SimpleNamespace(x=10, y=10))
    assert field._selected == set()


def test_deck_renders_top_card_back_image(field, root):
    # Create small fate and dynasty decks
    fate_cards = [FateCard(id=f"f{i}", name=f"Fate {i}", side=Side.FATE) for i in range(2)]
    dynasty_cards = [
        DynastyCard(id=f"d{i}", name=f"Dynasty {i}", side=Side.DYNASTY) for i in range(2)
    ]
    fate_deck = Deck.build(fate_cards)
    dynasty_deck = Deck.build(dynasty_cards)

    fate_tag = field.add_deck(fate_deck, x=80, y=300, label="Fate Deck")
    dynasty_tag = field.add_deck(dynasty_deck, x=240, y=300, label="Dynasty Deck")
    root.update_idletasks()
    root.update()

    # There should be image items for each deck tag or fallback if Pillow unavailable; we just assert items exist
    fate_items = field.find_withtag(fate_tag)
    dynasty_items = field.find_withtag(dynasty_tag)
    assert fate_items
    assert dynasty_items

    # Draw from fate deck and ensure deck re-renders (item count may change)
    field._on_double_click(SimpleNamespace(x=80, y=300))
    root.update_idletasks()
    root.update()
    after = len(field.find_withtag(fate_tag))
    assert after >= 1

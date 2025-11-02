import pytest

from app.gui.field import GameField
from app.gui.config import Hotkeys
from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side
from app.game_pieces.deck import Deck
from app.game_pieces.fate import FateCard
from app.game_pieces.dynasty import DynastyCard
from app.gui.constants import CARD_W, DRAW_OFFSET
from app.engine.zones import (
    HandZone,
    FateDiscardZone,
    ProvinceZone,
    DynastyDiscardZone,
    BattlefieldZone,
)
from tkinter import Event


class DummyEventNamespace(Event):
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


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


class TestCardInteractions:
    def test_double_click_card_toggles_bow(self, field, root, monkeypatch):
        card = L5RCard(id="c1", name="Test", side=Side.FATE)
        tag = field.add_card(card, x=100, y=100)
        root.update_idletasks()
        root.update()

        assert field._sprites[tag].card.bowed is False
        monkeypatch.setattr(field, "_resolve_tag_at", lambda e: tag)

        field._on_double_click(DummyEventNamespace(x=100, y=100))
        assert field._sprites[tag].card.bowed is True
        field._on_double_click(DummyEventNamespace(x=100, y=100))
        assert field._sprites[tag].card.bowed is False

    def test_drag_moves_card(self, field, root, monkeypatch):
        card = L5RCard(id="c2", name="Drag", side=Side.DYNASTY)
        tag = field.add_card(card, x=100, y=100)
        root.update_idletasks()
        root.update()

        monkeypatch.setattr(field, "_resolve_tag_at", lambda e: tag)
        field._on_press(DummyEventNamespace(x=100, y=100))
        field._on_motion(DummyEventNamespace(x=150, y=130))
        field._on_release(DummyEventNamespace(x=150, y=130))

        sprite = field._sprites[tag]
        assert (sprite.x, sprite.y) == (150, 130)


class TestDeckInteractions:
    def test_double_click_deck_draws_face_down(self, field, root, monkeypatch):
        cards = [FateCard(id=f"f{i}", name=f"Fate {i}", side=Side.FATE) for i in range(3)]
        deck = Deck.build(cards)

        deck_tag = field.add_deck(deck, x=200, y=250, label="Fate Deck")
        root.update_idletasks()
        root.update()

        start_count = len(deck.cards)
        before_tags = set(field._sprites.keys())

        monkeypatch.setattr(field, "_resolve_tag_at", lambda e: deck_tag)
        field._on_double_click(DummyEventNamespace(x=200, y=250))

        assert len(deck.cards) == start_count - 1
        after_tags = set(field._sprites.keys())
        new_tags = after_tags - before_tags
        assert len(new_tags) == 1
        new_tag = new_tags.pop()

        sprite = field._sprites[new_tag]
        assert sprite.card.face_up is False
        visual = field._decks[deck_tag]
        assert (sprite.x, sprite.y) == (visual.x - (CARD_W + DRAW_OFFSET), visual.y)

    def test_deck_renders_top_card_back_image(self, field, root):
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

        fate_items = field.find_withtag(fate_tag)
        dynasty_items = field.find_withtag(dynasty_tag)
        assert fate_items
        assert dynasty_items

        field._on_double_click(DummyEventNamespace(x=80, y=300))
        root.update_idletasks()
        root.update()
        after = len(field.find_withtag(fate_tag))
        assert after >= 1

    def test_press_on_fate_deck_starts_drag_and_creates_face_down_card(self, root, monkeypatch):
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
        monkeypatch.setattr(field, "_resolve_tag_at", lambda e: deck_tag)
        field._on_press(DummyEventNamespace(x=200, y=200))
        field._on_motion(DummyEventNamespace(x=400, y=200))
        assert len(deck.cards) == start_count - 1
        after_sprites = set(field._sprites.keys())
        new_tags = after_sprites - before_sprites
        assert len(new_tags) == 1
        new_tag = next(iter(new_tags))
        sprite = field._sprites[new_tag]
        assert sprite.card.face_up is False
        assert (sprite.x, sprite.y) == (400, 200)

    def test_drag_motion_moves_new_card_sprite_after_deck_press(self, root, monkeypatch):
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
        field._on_press(DummyEventNamespace(x=250, y=250))
        field._on_motion(DummyEventNamespace(x=100, y=100))
        new_tag = (set(field._sprites.keys()) - before_sprites).pop()
        field._on_motion(DummyEventNamespace(x=300, y=300))
        field._on_release(DummyEventNamespace(x=300, y=300))
        sprite = field._sprites[new_tag]
        assert (sprite.x, sprite.y) == (300, 300)


class TestContextMenuAndHotkeys:
    def test_context_menu_labels_and_actions(self, field, root, monkeypatch):
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
        assert labels[:3] == [
            f"Bow ({hk.bow})",
            f"Uninvert ({hk.invert})",
            f"Flip Down ({hk.flip})",
        ]
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
        assert labels[:3] == [
            f"Unbow ({hk.bow})",
            f"Uninvert ({hk.invert})",
            f"Flip Up ({hk.flip})",
        ]
        assert labels[-1] == "Send to"

        field._context_tag = tag
        field._build_context_menu_for(tag)
        field._invoke_context_shortcut(hk.bow)
        assert field._sprites[tag].card.bowed is False

    def test_keyboard_shortcuts_toggle_hovered_card_with_custom_hotkeys(
        self, field, root, monkeypatch
    ):
        hk = Hotkeys(bow="x", flip="y", invert="z")
        field.configure_hotkeys(hk)

        c = L5RCard(id="kb1", name="KB", side=Side.FATE)
        tag = field.add_card(c, x=160, y=160)
        root.update_idletasks()
        root.update()

        monkeypatch.setattr(field, "_resolve_tag_at", lambda e: tag)
        field._on_move(DummyEventNamespace(x=160, y=160))
        assert field._hover_tag == tag

        field._on_key(DummyEventNamespace(keysym=hk.bow))
        assert field._sprites[tag].card.bowed is True
        field._on_key(DummyEventNamespace(keysym=hk.bow))
        assert field._sprites[tag].card.bowed is False

        field._on_key(DummyEventNamespace(keysym=hk.flip))
        assert field._sprites[tag].card.face_up is False
        field._on_key(DummyEventNamespace(keysym=hk.flip))
        assert field._sprites[tag].card.face_up is True

        field._on_key(DummyEventNamespace(keysym=hk.invert))
        assert field._sprites[tag].card.inverted is True
        field._on_key(DummyEventNamespace(keysym=hk.invert))
        assert field._sprites[tag].card.inverted is False


class TestMarqueeAndSelection:
    def test_marquee_selects_multiple_cards_and_hotkeys_apply(self, field, root, monkeypatch):
        ctags = [
            field.add_card(L5RCard(id="m1", name="M1", side=Side.FATE), x=100, y=100),
            field.add_card(L5RCard(id="m2", name="M2", side=Side.FATE), x=160, y=120),
            field.add_card(L5RCard(id="m3", name="M3", side=Side.DYNASTY), x=260, y=200),
        ]
        root.update_idletasks()
        root.update()

        field._on_press(DummyEventNamespace(x=80, y=80))
        field._on_move(DummyEventNamespace(x=190, y=150))
        field._on_release(DummyEventNamespace(x=190, y=150))

        assert set(field._selected) == set(ctags[:2])

        field._on_key(DummyEventNamespace(keysym=Hotkeys().bow))
        assert all(field._sprites[t].card.bowed for t in ctags[:2])

        field._on_key(DummyEventNamespace(keysym=Hotkeys().flip))
        assert all(field._sprites[t].card.face_up is False for t in ctags[:2])

        field._on_escape(DummyEventNamespace())
        assert field._selected == set()

    def test_background_click_clears_selection(self, field, root):
        _ = field.add_card(L5RCard(id="s1", name="S1", side=Side.FATE), x=100, y=100)
        root.update_idletasks()
        root.update()
        field._on_press(DummyEventNamespace(x=100, y=100))
        field._on_press(DummyEventNamespace(x=10, y=10))
        assert field._selected == set()


class TestZoneInteractions:
    def test_zone_rendering(self, field, root):
        hand = HandZone()
        prov = ProvinceZone()
        hand_tag = field.add_zone(hand, x=100, y=100, w=200, h=120)
        prov_tag = field.add_zone(prov, x=500, y=300, w=200, h=120)
        root.update_idletasks()
        root.update()
        assert field.find_withtag(hand_tag)
        assert field.find_withtag(prov_tag)

    def test_drag_drop_into_hand_zone_adds_and_removes_sprite(self, root, monkeypatch):
        field = GameField(root, width=600, height=400)
        field.pack()
        root.update_idletasks()
        root.update()
        hand = HandZone()
        field.add_zone(hand, x=300, y=350, w=500, h=80)
        card = L5RCard(id="z1", name="Z1", side=Side.FATE)
        tag = field.add_card(card, x=100, y=100)
        root.update_idletasks()
        root.update()
        monkeypatch.setattr(field, "_resolve_tag_at", lambda e: tag)
        field._on_press(DummyEventNamespace(x=100, y=100))
        field._on_motion(DummyEventNamespace(x=300, y=330))
        field._on_release(DummyEventNamespace(x=300, y=330))
        assert tag not in field._sprites
        assert len(hand) == 1

    def test_drag_drop_into_fate_discard_zone(self, root, monkeypatch):
        field = GameField(root, width=600, height=400)
        field.pack()
        root.update_idletasks()
        root.update()
        fate_disc = FateDiscardZone()
        field.add_zone(fate_disc, x=500, y=200, w=120, h=160)
        card = L5RCard(id="z2", name="Z2", side=Side.FATE)
        tag = field.add_card(card, x=400, y=100)
        root.update_idletasks()
        root.update()
        monkeypatch.setattr(field, "_resolve_tag_at", lambda e: tag)
        field._on_press(DummyEventNamespace(x=400, y=100))
        field._on_motion(DummyEventNamespace(x=500, y=200))
        field._on_release(DummyEventNamespace(x=500, y=200))
        assert tag not in field._sprites
        assert len(fate_disc) == 1

    def test_invalid_drop_fate_into_province_is_ignored(self, root, monkeypatch):
        field = GameField(root, width=600, height=400)
        field.pack()
        root.update_idletasks()
        root.update()
        prov = ProvinceZone()
        field.add_zone(prov, x=300, y=200, w=200, h=100)
        card = L5RCard(id="pf1", name="PF1", side=Side.FATE)
        tag = field.add_card(card, x=100, y=100)
        root.update_idletasks()
        root.update()
        monkeypatch.setattr(field, "_resolve_tag_at", lambda e: tag)
        field._on_press(DummyEventNamespace(x=100, y=100))
        field._on_motion(DummyEventNamespace(x=300, y=200))
        field._on_release(DummyEventNamespace(x=300, y=200))
        assert tag in field._sprites
        assert len(prov) == 0

    def test_invalid_drop_dynasty_into_hand_is_ignored(self, root, monkeypatch):
        field = GameField(root, width=600, height=400)
        field.pack()
        root.update_idletasks()
        root.update()
        hand = HandZone()
        field.add_zone(hand, x=300, y=350, w=500, h=80)
        card = L5RCard(id="ph1", name="PH1", side=Side.DYNASTY)
        tag = field.add_card(card, x=100, y=100)
        root.update_idletasks()
        root.update()
        monkeypatch.setattr(field, "_resolve_tag_at", lambda e: tag)
        field._on_press(DummyEventNamespace(x=100, y=100))
        field._on_motion(DummyEventNamespace(x=300, y=350))
        field._on_release(DummyEventNamespace(x=300, y=350))
        assert tag in field._sprites
        assert len(hand) == 0

    def test_clear_selection_after_drop_does_not_error(self, root, monkeypatch):
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
        monkeypatch.setattr(field, "_resolve_tag_at", lambda e: tag)
        field._on_press(DummyEventNamespace(x=100, y=100))
        assert tag in field._selected
        field._on_motion(DummyEventNamespace(x=300, y=350))
        field._on_release(DummyEventNamespace(x=300, y=350))
        assert tag not in field._sprites
        monkeypatch.setattr(field, "_resolve_tag_at", lambda e: None)
        field._on_press(DummyEventNamespace(x=10, y=10))
        assert field._selected == set()

    def test_hover_province_press_c_destroys_and_moves_to_discard(self, root, monkeypatch):
        field = GameField(root, width=600, height=400)
        field.pack()
        root.update_idletasks()
        root.update()
        prov1 = ProvinceZone()
        prov2 = ProvinceZone()
        prov1_tag = field.add_zone(prov1, x=150, y=200, w=120, h=160)
        field.add_zone(prov2, x=300, y=200, w=120, h=160)
        discard = DynastyDiscardZone()
        field.add_zone(discard, x=500, y=200, w=120, h=160)
        c = DynastyCard(id="dzz", name="DZ", side=Side.DYNASTY)
        prov1.add(c)
        monkeypatch.setattr(field, "_resolve_tag_at", lambda e: prov1_tag)
        field._on_move(DummyEventNamespace(x=150, y=200))
        hk = Hotkeys()
        field._on_key(DummyEventNamespace(keysym=hk.destroy))
        assert prov1_tag not in field._zones
        assert len(discard) == 1
        assert discard.cards[-1].face_up is True

    def test_hover_province_press_l_fills_from_dynasty_deck(self, root, monkeypatch):
        field = GameField(root, width=600, height=400)
        field.pack()
        root.update_idletasks()
        root.update()
        prov = ProvinceZone()
        prov_tag = field.add_zone(prov, x=300, y=200, w=120, h=160)
        cards = [DynastyCard(id="d1", name="D1", side=Side.DYNASTY)]
        deck = Deck.build(cards)
        field.add_deck(deck, x=100, y=100, label="Dynasty Deck")
        monkeypatch.setattr(field, "_resolve_tag_at", lambda e: prov_tag)
        field._on_move(DummyEventNamespace(x=300, y=200))
        hk = Hotkeys()
        field._on_key(DummyEventNamespace(keysym=hk.fill))
        assert len(prov) == 1
        top = prov.cards[-1]
        assert top.face_up is False
        assert len(deck.cards) == 0


class TestBattlefieldTracking:
    def test_battlefield_tracks_added_cards(self, root):
        field = GameField(root, width=400, height=300)
        field.pack()
        root.update_idletasks()
        root.update()
        bf = BattlefieldZone()
        field.set_battlefield_zone(bf)
        c1 = L5RCard(id="b1", name="Battle1", side=Side.FATE)
        c2 = L5RCard(id="b2", name="Battle2", side=Side.DYNASTY)
        field.add_card(c1, x=100, y=100)
        field.add_card(c2, x=200, y=120)
        assert len(bf) == 2
        assert bf.cards[-2].id == "b1"
        assert bf.cards[-1].id == "b2"

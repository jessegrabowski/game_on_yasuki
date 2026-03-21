import tkinter as tk

from app.gui.field_view import FieldView
from app.gui.config import Hotkeys
from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side
from app.game_pieces.deck import Deck
from app.engine.zones import HandZone, ProvinceZone, DynastyDiscardZone
from app.gui.services.actions import ActionContext, REGISTRY as ACTIONS

from tests.gui.conftest import DummyEventNamespace


class TestCardInteractions:
    def test_double_click_card_toggles_bow(self, field, root, monkeypatch):
        card = L5RCard(id="c1", name="Test", side=Side.FATE)
        tag = field.add_card(card, x=100, y=100)
        root.update_idletasks()
        root.update()
        assert field._sprites[tag].card.bowed is False
        monkeypatch.setattr(field, "resolve_tag_at", lambda e: tag)
        field._controller.on_double_click(DummyEventNamespace(x=100, y=100))
        assert field._sprites[tag].card.bowed is True
        field._controller.on_double_click(DummyEventNamespace(x=100, y=100))
        assert field._sprites[tag].card.bowed is False

    def test_double_click_on_province_card_does_not_bow(self, root, monkeypatch):
        # Setup field and province containing a dynasty card
        field = FieldView(root, width=800, height=600)
        province = ProvinceZone(name="Province 2")
        ztag = field.add_zone(province, x=320, y=200, w=120, h=160)
        card = L5RCard(id="dp1", name="Dynasty Prov", side=Side.DYNASTY)
        province.add(card)
        field.redraw_zone(ztag)
        # Create a sprite for the same card (so controller resolves a card target)
        stag = field.add_card(card, x=320, y=200)
        # Remove from battlefield zone registry if it was added there by add_card
        if getattr(field, "_battlefield_zone", None) is not None:
            try:
                field._battlefield_zone.remove(card)
            except Exception:
                pass
        root.update_idletasks()
        root.update()
        assert card.bowed is False
        # Simulate double-click on the card: actions gating should prevent bow in province
        monkeypatch.setattr(field, "resolve_tag_at", lambda e: stag)
        field._controller.on_double_click(DummyEventNamespace(x=320, y=200))
        assert card.bowed is False
        # Try again to ensure repeated double-clicks still no-op
        field._controller.on_double_click(DummyEventNamespace(x=320, y=200))
        assert card.bowed is False

    def test_card_in_province_cannot_be_bowed(self, root):
        # Setup a field with a province and a dynasty card in it
        field = FieldView(root, width=800, height=600)
        province = ProvinceZone(name="Province 1")
        ztag = field.add_zone(province, x=300, y=200, w=100, h=150)

        card = L5RCard(id="d1", name="Dynasty 1", side=Side.DYNASTY)
        province.add(card)
        field.redraw_zone(ztag)

        # Create a battlefield sprite and then remove it from battlefield; we only need sprites map for actions ctx
        # Instead, build a sprite directly to simulate selection context
        # Place a visual sprite representing the same card (so actions can reference it)
        stag = field.add_card(card, x=320, y=220)
        # Remove from battlefield zone registry if present to avoid duplication
        if getattr(field, "_battlefield_zone", None) is not None:
            try:
                field._battlefield_zone.remove(card)
            except Exception:
                pass

        # Ensure our context targets the sprite and carries owner (None -> allowed by owner rule)
        ctx = ActionContext(card_tag=stag, owner=None)
        act = ACTIONS["card.toggle_bow"]

        # The action should be disabled because the card is in a province
        assert act.when(field, ctx) is False

        # Try to invoke run anyway — should be a no-op because we respect when() in controller paths
        # For direct invocation safety, only call when allowed; emulate controller behavior
        if act.when(field, ctx):
            act.run(field, ctx)
        # Card remains unbowed
        assert card.bowed is False

    def test_drag_moves_card(self, field, root, monkeypatch):
        card = L5RCard(id="c2", name="Drag", side=Side.DYNASTY)
        tag = field.add_card(card, x=100, y=100)
        root.update_idletasks()
        root.update()
        monkeypatch.setattr(field, "resolve_tag_at", lambda e: tag)
        field._controller.on_press(DummyEventNamespace(x=100, y=100))
        field._controller.on_motion(DummyEventNamespace(x=150, y=130))
        field._controller.on_release(DummyEventNamespace(x=150, y=130))
        sprite = field._sprites[tag]
        assert (sprite.x, sprite.y) == (150, 130)


class TestContextMenuAndHotkeys:
    def test_context_menu_discard_moves_to_dynasty_discard(self, field, root, monkeypatch):
        monkeypatch.setattr(tk.Menu, "tk_popup", lambda self, x, y: None)
        prov = ProvinceZone()
        prov_tag = field.add_zone(prov, x=220, y=220, w=140, h=160)
        discard = DynastyDiscardZone()
        _ = field.add_zone(discard, x=500, y=220, w=140, h=160)
        c = L5RCard(id="pd1", name="PD1", side=Side.DYNASTY)
        c.turn_face_down()
        prov.add(c)
        root.update_idletasks()
        root.update()
        monkeypatch.setattr(field, "resolve_tag_at", lambda e: prov_tag)
        field._controller.on_context(DummyEventNamespace(x_root=10, y_root=10))
        menu = field._controller._context_menu
        end = menu.index("end") or -1
        for i in range(end + 1):
            if menu.entrycget(i, "label").startswith("Discard"):
                menu.invoke(i)
                break
        assert len(prov) == 0
        assert len(discard) == 1
        assert discard.cards[-1].face_up is True

    def test_negative_discard_no_effect_for_non_province_or_missing_discard(
        self, field, root, monkeypatch
    ):
        # Setup a HandZone (non-province) and add a dynasty card
        hand = HandZone()
        hand_tag = field.add_zone(hand, x=200, y=350, w=300, h=80)
        c = L5RCard(id="np1", name="NP1", side=Side.DYNASTY)
        hand.add(c)
        root.update_idletasks()
        root.update()
        # Hover hand and press d: should not discard
        monkeypatch.setattr(field, "resolve_tag_at", lambda e: hand_tag)
        field._controller.on_move(DummyEventNamespace(x=200, y=350))
        before_hand = len(hand)
        _ = [z for z in field._zones.values() if isinstance(z.zone, DynastyDiscardZone)]
        field._controller.on_key(DummyEventNamespace(keysym=Hotkeys().invert))
        assert len(hand) == before_hand
        # Now test province with no discard zone exists
        prov = ProvinceZone()
        prov_tag = field.add_zone(prov, x=100, y=200, w=120, h=160)
        dcard = L5RCard(id="np2", name="NP2", side=Side.DYNASTY)
        prov.add(dcard)
        monkeypatch.setattr(field, "resolve_tag_at", lambda e: prov_tag)
        field._controller.on_move(DummyEventNamespace(x=100, y=200))
        field._controller.on_key(DummyEventNamespace(keysym=Hotkeys().invert))
        # Card should still remain in province since no discard zone
        assert len(prov) == 1


class TestMarqueeAndSelection:
    def test_marquee_box_expands_and_multi_action(self, field, root):
        # Place two cards and marquee-select them, verify the marquee rectangle expands
        t1 = field.add_card(L5RCard(id="mqa1", name="MQA1", side=Side.FATE), x=120, y=120)
        t2 = field.add_card(L5RCard(id="mqa2", name="MQA2", side=Side.FATE), x=180, y=140)
        root.update_idletasks()
        root.update()
        # Start marquee at top-left of both, then drag to bottom-right
        x0, y0 = 80, 80
        x1, y1 = 220, 200
        field._controller.on_press(DummyEventNamespace(x=x0, y=y0))
        field._controller.on_motion(DummyEventNamespace(x=x1, y=y1))
        # The marquee rectangle should exist and have expanded coords
        items = field.find_withtag("marquee")
        assert items, "Marquee rectangle not created"
        rid = items[0]
        cx0, cy0, cx1, cy1 = field.coords(rid)
        assert (cx0, cy0) == (x0, y0)
        assert (cx1, cy1) == (x1, y1)
        # Release to end marquee and finalize selection
        field._controller.on_release(DummyEventNamespace(x=x1, y=y1))
        assert set(field._selected) == {t1, t2}
        # Act on multiple: bow both via hotkey
        hk = Hotkeys()
        field._controller.on_key(DummyEventNamespace(keysym=hk.bow))
        assert field._sprites[t1].card.bowed is True
        assert field._sprites[t2].card.bowed is True


class TestZoneAndHandInteractions:
    def test_hover_province_press_d_discards_face_up(self, field, root, monkeypatch):
        # Setup province with a face-down dynasty card and a dynasty discard zone
        prov = ProvinceZone()
        prov_tag = field.add_zone(prov, x=200, y=200, w=120, h=160)
        discard = DynastyDiscardZone()
        _ = field.add_zone(discard, x=500, y=200, w=120, h=160)
        c = L5RCard(id="ddisc", name="DD", side=Side.DYNASTY)
        # Ensure it's face-down in province
        c.turn_face_down()
        prov.add(c)
        root.update_idletasks()
        root.update()
        # Hover province
        monkeypatch.setattr(field, "resolve_tag_at", lambda e: prov_tag)
        field._controller.on_move(DummyEventNamespace(x=200, y=200))
        # Press invert hotkey (d) to discard
        hk = Hotkeys()
        field._controller.on_key(DummyEventNamespace(keysym=hk.invert))
        # Assert province is empty and discard has the card face-up
        assert len(prov) == 0
        assert len(discard) == 1
        assert discard.cards[-1].face_up is True


class TestDeckContextMenu:
    def test_deck_context_menu_create_province_click(self, field, root, monkeypatch):
        """Right-click a dynasty deck, select Create Province from the menu, and assert a province is created."""
        monkeypatch.setattr(tk.Menu, "tk_popup", lambda self, x, y: None)
        # Build a simple dynasty deck and add it
        from app.game_pieces.dynasty import DynastyCard

        cards = [DynastyCard(id=f"d{i}", name=f"D{i}", side=Side.DYNASTY) for i in range(3)]
        deck = Deck.build(cards)
        deck_tag = field.add_deck(deck, x=220, y=160, label="Dynasty Deck")
        root.update_idletasks()
        root.update()
        # Ensure no provinces initially
        provinces_before = [z for z in field._zones.values() if isinstance(z.zone, ProvinceZone)]
        assert len(provinces_before) == 0
        # Open context on deck
        monkeypatch.setattr(field, "resolve_tag_at", lambda e: deck_tag)
        field._controller.on_context(DummyEventNamespace(x_root=10, y_root=10))
        menu = field._controller._context_menu
        # Find Create Province entry and invoke it
        end = menu.index("end") or -1
        invoked = False
        for i in range(end + 1):
            label = menu.entrycget(i, "label")
            if label.startswith("Create Province"):
                # Ensure it's enabled and invoke
                state = menu.entrycget(i, "state")
                assert state == "normal"
                menu.invoke(i)
                invoked = True
                break
        assert invoked is True
        # After invoking, there should be at least one province
        provinces_after = [z for z in field._zones.values() if isinstance(z.zone, ProvinceZone)]
        assert len(provinces_after) >= 1

    def test_deck_context_menu_create_province_disabled_for_non_dynasty(
        self, field, root, monkeypatch
    ):
        """Ensure Create Province menu item is disabled for a Fate deck."""
        monkeypatch.setattr(tk.Menu, "tk_popup", lambda self, x, y: None)
        from app.game_pieces.fate import FateCard

        cards = [FateCard(id=f"f{i}", name=f"F{i}", side=Side.FATE) for i in range(2)]
        deck = Deck.build(cards)
        deck_tag = field.add_deck(deck, x=260, y=180, label="Fate Deck")
        root.update_idletasks()
        root.update()
        monkeypatch.setattr(field, "resolve_tag_at", lambda e: deck_tag)
        field._controller.on_context(DummyEventNamespace(x_root=10, y_root=10))
        menu = field._controller._context_menu
        end = menu.index("end") or -1
        found = False
        for i in range(end + 1):
            label = menu.entrycget(i, "label")
            if label.startswith("Create Province"):
                found = True
                state = menu.entrycget(i, "state")
                assert state == "disabled"
        assert found is True

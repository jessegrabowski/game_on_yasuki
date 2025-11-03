import tkinter as tk

from app.gui.field_view import FieldView
from app.gui.config import Hotkeys
from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side
from app.game_pieces.deck import Deck
from app.game_pieces.fate import FateCard
from app.gui.constants import CARD_H
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


class TestDeckInteractions:
    def test_double_click_deck_draws_to_hand_if_fate(self, field, root, monkeypatch):
        cards = [FateCard(id=f"f{i}", name=f"Fate {i}", side=Side.FATE) for i in range(3)]
        deck = Deck.build(cards)
        deck_tag = field.add_deck(deck, x=200, y=250, label="Fate Deck")
        hand = HandZone()
        _ = field.add_zone(hand, x=300, y=350, w=500, h=80)
        root.update_idletasks()
        root.update()
        start_count = len(deck.cards)
        before_hand_count = len(hand.cards)
        monkeypatch.setattr(field, "resolve_tag_at", lambda e: deck_tag)
        field._controller.on_double_click(DummyEventNamespace(x=200, y=250))
        assert len(deck.cards) == start_count - 1
        assert len(hand.cards) == before_hand_count + 1
        assert hand.cards[-1].face_up is True

    def test_press_on_deck_then_drag_creates_face_down_sprite(self, root, monkeypatch):
        field = FieldView(root, width=600, height=400)
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
        monkeypatch.setattr(field, "resolve_tag_at", lambda e: deck_tag)
        field._controller.on_press(DummyEventNamespace(x=200, y=200))
        field._controller.on_motion(DummyEventNamespace(x=400, y=200))
        assert len(deck.cards) == start_count - 1
        new_tags = set(field._sprites.keys()) - before_sprites
        assert len(new_tags) == 1
        new_tag = next(iter(new_tags))
        sprite = field._sprites[new_tag]
        assert sprite.card.face_up is False
        assert (sprite.x, sprite.y) == (400, 200)


class TestDeckHoverHotkeys:
    def test_hover_hotkeys_on_fate_and_dynasty(self, field, root, monkeypatch):
        fate_cards = [FateCard(id=f"ff{i}", name=f"Fate {i}", side=Side.FATE) for i in range(3)]
        fate_deck = Deck.build(fate_cards)
        fate_tag = field.add_deck(fate_deck, x=180, y=220, label="Fate Deck")
        hand_tag = field.add_zone(HandZone(), x=320, y=360, w=500, h=80)
        if fate_deck.cards:
            fate_deck.cards[-1].turn_face_down()
        root.update_idletasks()
        root.update()
        hk = Hotkeys()
        monkeypatch.setattr(field, "resolve_tag_at", lambda e: fate_tag)
        field._controller.on_move(DummyEventNamespace(x=180, y=220))
        assert field._controller._hover_deck_tag == fate_tag
        field._controller.on_key(DummyEventNamespace(keysym=hk.flip))
        assert fate_deck.cards[-1].face_up is True
        # shuffle and inspect
        shuffled = {"called": False}

        def _mark_shuffle():
            shuffled["called"] = True

        fate_deck.shuffle = _mark_shuffle  # type: ignore
        field._controller.on_key(DummyEventNamespace(keysym=hk.shuffle))
        assert shuffled["called"] is True
        before = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        field._controller.on_key(DummyEventNamespace(keysym=hk.inspect))
        after = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        assert len(after) == len(before) + 1
        new_win = next(w for w in after if w not in before)
        new_win.destroy()
        # Draw goes to hand
        hand = field._hands[hand_tag].zone
        sd, sh = len(fate_deck.cards), len(hand.cards)
        field._controller.on_key(DummyEventNamespace(keysym=hk.draw))
        assert (
            len(fate_deck.cards) == sd - 1 and len(hand.cards) == sh + 1 and hand.cards[-1].face_up
        )


class TestContextMenuAndHotkeys:
    def test_context_menu_and_shortcuts(self, field, root, monkeypatch):
        monkeypatch.setattr(tk.Menu, "tk_popup", lambda self, x, y: None)

        hk = Hotkeys(bow="b", flip="f", invert="d")
        field.configure_hotkeys(hk)
        card = L5RCard(id="c3", name="Menu", side=Side.FATE)
        tag = field.add_card(card, x=120, y=120)
        root.update_idletasks()
        root.update()
        monkeypatch.setattr(field, "resolve_tag_at", lambda e: tag)
        field._controller.on_context(DummyEventNamespace(x_root=10, y_root=10))
        menu = field._controller._context_menu
        labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)]
        assert labels[:3] == [f"Bow ({hk.bow})", f"Invert ({hk.invert})", f"Flip Down ({hk.flip})"]
        # invert
        field._controller.on_key(DummyEventNamespace(keysym=hk.invert))
        field._controller.on_context(DummyEventNamespace(x_root=10, y_root=10))
        labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)]
        assert labels[1].startswith("Uninvert")

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
        # Open context on province and click Discard
        monkeypatch.setattr(field, "resolve_tag_at", lambda e: prov_tag)
        field._controller.on_context(DummyEventNamespace(x_root=10, y_root=10))
        menu = field._controller._context_menu
        # Find the "Discard" entry and invoke it
        end = menu.index("end") or -1
        for i in range(end + 1):
            if menu.entrycget(i, "label").startswith("Discard"):
                menu.invoke(i)
                break
        # Assert province empty, discard has face-up card
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
    def test_drag_drop_into_hand_zone(self, root, monkeypatch):
        field = FieldView(root, width=600, height=400)
        field.pack()
        root.update_idletasks()
        root.update()
        hand = HandZone()
        field.add_zone(hand, x=300, y=350, w=500, h=80)
        card = L5RCard(id="z1", name="Z1", side=Side.FATE)
        tag = field.add_card(card, x=100, y=100)
        root.update_idletasks()
        root.update()
        monkeypatch.setattr(field, "resolve_tag_at", lambda e: tag)
        field._controller.on_press(DummyEventNamespace(x=100, y=100))
        field._controller.on_motion(DummyEventNamespace(x=300, y=330))
        field._controller.on_release(DummyEventNamespace(x=300, y=330))
        assert tag not in field._sprites and len(hand) == 1

    def test_hand_drag_exit_and_reinsert(self, field, root, monkeypatch):
        hand = HandZone()
        hand_tag = field.add_zone(hand, x=300, y=350, w=500, h=80)
        c1 = L5RCard(id="r1", name="R1", side=Side.FATE)
        c2 = L5RCard(id="r2", name="R2", side=Side.FATE)
        hand.add(c1)
        hand.add(c2)
        field._redraw_zone(hand_tag)
        root.update_idletasks()
        root.update()
        hv = field._hands[hand_tag]
        x0, y0 = hv.center_for_index(0)
        before = set(field._sprites.keys())
        monkeypatch.setattr(field, "resolve_tag_at", lambda e: hand_tag)
        field._controller.on_press(DummyEventNamespace(x=x0, y=y0))
        field._controller.on_move(DummyEventNamespace(x=hv.x, y=hv.bbox[1] - (CARD_H // 2) - 10))
        root.update_idletasks()
        root.update()
        x1, y1 = hv.center_for_index(1)
        field._controller.on_motion(DummyEventNamespace(x=x1, y=y1))
        field._controller.on_release(DummyEventNamespace(x=x1, y=y1))
        after = set(field._sprites.keys())
        assert after == before
        assert [c.id for c in hand.cards] == ["r2", "r1"]

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

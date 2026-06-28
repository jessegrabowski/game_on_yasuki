from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import BoardPos, DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.intents import Bow, DestroyProvince, Draw, FlipDeckTop, MoveCard
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_gui.tags import card_tag, deck_tag, zone_tag
from yasuki_gui.visuals.cardface import HiddenFace


def _province_keys(state, seat):
    return [k for k in state.zones if k.owner is seat and k.role is ZoneRole.PROVINCE]


class TestLoadState:
    def test_visuals_mirror_state_membership(self, loaded):
        field, state = loaded
        # One sprite per battlefield card, keyed by card id.
        assert set(field.sprites) == {card_tag(c.id) for c in state.battlefield.cards}
        # One deck visual per deck key.
        assert set(field.decks) == {deck_tag(k) for k in state.decks}
        # Hands and other zones split across the two maps, together covering every zone key.
        assert set(field.hands) | set(field.zones) == {zone_tag(k) for k in state.zones}

    def test_tags_map_back_to_keys(self, loaded):
        field, _ = loaded
        for tag, key in field._tag_to_key.items():
            expected = deck_tag(key) if isinstance(key, DeckKey) else zone_tag(key)
            assert tag == expected


class TestDispatchReconcile:
    def test_draw_grows_hand(self, loaded):
        field, state = loaded
        hand = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
        before = len(hand.cards)
        events = field.dispatch(Draw(DeckKey(PlayerId.P1, Side.FATE)))
        assert events
        assert len(hand.cards) == before + 1

    def test_dynasty_draw_with_full_provinces_adds_battlefield_sprite(self, loaded):
        field, state = loaded
        before = len(field.sprites)
        field.dispatch(Draw(DeckKey(PlayerId.P1, Side.DYNASTY)))
        assert len(field.sprites) == before + 1
        assert set(field.sprites) == {card_tag(c.id) for c in state.battlefield.cards}

    def test_bow_keeps_sprite_and_marks_card(self, loaded):
        field, state = loaded
        field.dispatch(Bow(("P1-SH",)))
        assert state.cards_by_id["P1-SH"].bowed is True
        assert card_tag("P1-SH") in field.sprites

    def test_move_to_discard_removes_sprite_and_lands_in_zone(self, loaded):
        field, state = loaded
        field.dispatch(Draw(DeckKey(PlayerId.P1, Side.DYNASTY)))
        card = state.battlefield.cards[-1]
        discard = ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)
        field.dispatch(MoveCard(card.id, discard))
        assert card_tag(card.id) not in field.sprites
        assert card in state.zones[discard].cards

    def test_destroy_province_removes_zone_visual(self, loaded):
        field, state = loaded
        key = _province_keys(state, PlayerId.P1)[0]
        tag = zone_tag(key)
        assert tag in field.zones
        field.dispatch(DestroyProvince(key))
        assert tag not in field.zones
        assert key not in state.zones

    def test_rejected_intent_returns_no_events(self, loaded):
        field, state = loaded
        empty = DeckKey(PlayerId.P1, Side.FATE)
        state.decks[empty].cards.clear()
        assert field.dispatch(FlipDeckTop(empty)) == []


class TestRulesModeRender:
    def _rules_field(self, loaded):
        """Switch the loaded field into rules mode rendering a small game with a face-down P2 card
        on the battlefield, projected for P1."""
        field, _ = loaded
        state = TableState.empty_two_seat()
        secret = L5RCard(id="P2-bf", name="Ambush", side=Side.DYNASTY, owner=PlayerId.P2)
        secret.turn_face_down()
        state.cards_by_id["P2-bf"] = secret
        state.battlefield.add(secret)
        state.positions["P2-bf"] = BoardPos(10.0, 10.0)
        session = EngineSession.start(state, PlayerId.P1)
        field.render_snapshot(session.project(PlayerId.P1).table, PlayerId.P1)
        return field

    def test_projection_renders_the_opponent_card_as_hidden(self, loaded):
        field = self._rules_field(loaded)
        tag = card_tag("P2-bf")
        assert tag in field.sprites  # the card still renders so it can be animated
        assert isinstance(field.sprites[tag].card, HiddenFace)  # but as a back to P1

    def test_dispatch_is_a_noop_in_rules_mode(self, loaded):
        field = self._rules_field(loaded)
        assert field.dispatch(Bow(("P2-bf",))) == []


class TestInlineDiscard:
    def test_toggle_tracks_selection_and_notifies(self, loaded):
        field, _ = loaded
        changes = []
        field.on_discard_selection_changed = lambda: changes.append(1)

        field.begin_discard(2)
        assert field.discard_needed == 2
        field.toggle_discard_card("c1")
        field.toggle_discard_card("c2")
        assert field.discard_selection == frozenset({"c1", "c2"})
        field.toggle_discard_card("c1")  # clicking again deselects
        assert field.discard_selection == frozenset({"c2"})
        assert len(changes) == 3  # one notification per toggle

        field.end_discard()
        assert field.discard_needed is None
        assert field.discard_selection == frozenset()

    def test_selection_reaches_the_human_hand_visual(self, loaded):
        field, _ = loaded
        field.dispatch(Draw(DeckKey(PlayerId.P1, Side.FATE)))  # a real card in hand
        hand_tag = zone_tag(ZoneKey(PlayerId.P1, ZoneRole.HAND))
        card_id = field.hands[hand_tag].cards[0].id

        field.begin_discard(1)
        field.toggle_discard_card(card_id)
        field.reconcile_all()

        # The field feeds the selection to the hand it renders, so the border can be drawn.
        assert card_id in field.hands[hand_tag].selected_ids


class TestDebugSeatFlip:
    def test_flip_renders_from_other_seat(self, loaded):
        field, _ = loaded
        assert field._flipped is False
        field.seat = PlayerId.P2
        field.reconcile_all()
        assert field._flipped is True
        assert card_tag("P2-SH") in field.sprites

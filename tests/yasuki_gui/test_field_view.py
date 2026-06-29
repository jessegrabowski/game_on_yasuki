from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    BoardPos,
    DeckKey,
    TableState,
    UNPLACED_BOARD_POS,
    ZoneKey,
    ZoneRole,
)
from yasuki_core.engine.intents import Bow, DestroyProvince, Draw, FlipDeckTop, MoveCard
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_gui.tags import card_tag, deck_tag, zone_tag
from yasuki_gui.visuals.cardface import HiddenFace


def _province_keys(state, seat):
    return [k for k in state.zones if k.owner is seat and k.role is ZoneRole.PROVINCE]


class TestLoadState:
    def test_only_in_play_zones_render_on_the_board(self, loaded):
        field, state = loaded
        # One sprite per battlefield card, keyed by card id.
        assert set(field.sprites) == {card_tag(c.id) for c in state.battlefield.cards}
        # Only the viewer's own hand is drawn (the opponent's is never shown).
        assert set(field.hands) == {zone_tag(ZoneKey(field.seat, ZoneRole.HAND))}
        # Every province (both seats) is drawn; no discard/banish zones.
        assert set(field.zones) == {zone_tag(k) for k in state.zones if k.role is ZoneRole.PROVINCE}

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


class TestHomeRow:
    def test_unplaced_cards_get_distinct_positions(self, loaded):
        field, state = loaded
        # P1's stronghold starts unplaced; add a second unplaced P1 card beside it.
        extra = L5RCard(id="P1-extra", name="Sensei", side=Side.DYNASTY, owner=PlayerId.P1)
        state.cards_by_id["P1-extra"] = extra
        state.battlefield.add(extra)
        state.positions["P1-extra"] = UNPLACED_BOARD_POS
        field.reconcile_all()

        stronghold = field.sprites[card_tag("P1-SH")]
        sensei = field.sprites[card_tag("P1-extra")]
        assert stronghold.x != sensei.x  # the home row steps them apart, not stacked


class TestOffBoardReads:
    def test_deck_summary_reports_count_and_top(self, loaded):
        field, state = loaded
        key = DeckKey(PlayerId.P1, Side.FATE)
        count, top = field.deck_summary(key)
        assert count == len(state.decks[key].cards)
        assert top is not None  # the dealt deck has cards

    def test_zone_render_cards_reads_a_discard_pile(self, loaded):
        field, state = loaded
        field.dispatch(Draw(DeckKey(PlayerId.P1, Side.DYNASTY)))
        card = state.battlefield.cards[-1]
        discard = ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)
        field.dispatch(MoveCard(card.id, discard))
        assert [c.id for c in field.zone_render_cards(discard)] == [card.id]

    def test_hand_count_tracks_the_hand(self, loaded):
        field, _ = loaded
        before = field.hand_count(PlayerId.P1)
        field.dispatch(Draw(DeckKey(PlayerId.P1, Side.FATE)))
        assert field.hand_count(PlayerId.P1) == before + 1

    def test_rules_mode_shows_opponent_counts_but_hides_hand_identities(self, loaded):
        field, _ = loaded
        state = TableState.empty_two_seat()
        deck = state.decks[DeckKey(PlayerId.P2, Side.FATE)]
        for i in range(3):
            card = L5RCard(id=f"P2-f{i}", name="F", side=Side.FATE, owner=PlayerId.P2)
            state.cards_by_id[card.id] = card
            deck.cards.append(card)
        held = L5RCard(id="P2-h", name="Secret", side=Side.FATE, owner=PlayerId.P2)
        state.cards_by_id["P2-h"] = held
        state.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)].add(held)
        session = EngineSession.start(state, PlayerId.P1)
        field.render_snapshot(session.project(PlayerId.P1).table, PlayerId.P1)

        # P1 reads the opponent's public counts through the projection...
        assert field.deck_summary(DeckKey(PlayerId.P2, Side.FATE))[0] == 3
        assert field.hand_count(PlayerId.P2) == 1
        # ...but the held card's identity stays hidden — it comes back as a back, not its face.
        hand = field.zone_render_cards(ZoneKey(PlayerId.P2, ZoneRole.HAND))
        assert [type(card) for card in hand] == [HiddenFace]


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


class TestDecisionSelection:
    def test_toggle_tracks_candidates_and_notifies(self, loaded):
        field, _ = loaded
        changes = []
        field.on_selection_changed = lambda: changes.append(1)

        field.begin_selection(["c1", "c2"])
        assert field.selecting is True
        field.toggle_selection("c1")
        field.toggle_selection("c2")
        assert field.selection == frozenset({"c1", "c2"})
        field.toggle_selection("c1")  # clicking again deselects
        assert field.selection == frozenset({"c2"})
        field.toggle_selection("nope")  # a non-candidate is ignored, no notification
        assert field.selection == frozenset({"c2"})
        assert len(changes) == 3  # one notification per accepted toggle

        field.end_selection()
        assert field.selecting is False
        assert field.selection == frozenset()

    def test_selection_reaches_the_human_hand_visual(self, loaded):
        field, _ = loaded
        field.dispatch(Draw(DeckKey(PlayerId.P1, Side.FATE)))  # a real card in hand
        hand_tag = zone_tag(ZoneKey(PlayerId.P1, ZoneRole.HAND))
        card_id = field.hands[hand_tag].cards[0].id

        field.begin_selection([card_id])
        field.toggle_selection(card_id)
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

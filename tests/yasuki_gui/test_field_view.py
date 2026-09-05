import pytest

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
from yasuki_core.engine.rules.actions import ActivateAbility
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.decisions import ChooseDistribution, DecisionResponse
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_gui.constants import ATTACH_STACK_OFFSET, CARD_H, CARD_W, HOME_STACK_OFFSET
from yasuki_gui.field_view import ALLOCATION_TAG
from yasuki_gui.layout import province_positions
from yasuki_gui.tags import allocation_tag, card_tag, deck_tag, zone_tag
from yasuki_gui.visuals.cardface import HiddenFace

from tests.yasuki_core.engine.builders import (
    personality,
    put_in_play,
    token_template,
    two_seat_game,
)
from yasuki_core.game_pieces.prints import (
    AttachmentPrint,
    CardPrint,
    DynastyPrint,
    HoldingPrint,
    PersonalityPrint,
    SenseiPrint,
    WindPrint,
)


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
        extra = L5RCard.of(
            CardPrint, id="P1-extra", name="Sensei", side=Side.DYNASTY, owner=PlayerId.P1
        )
        state.cards_by_id["P1-extra"] = extra
        state.battlefield.add(extra)
        state.positions["P1-extra"] = UNPLACED_BOARD_POS
        field.reconcile_all()

        stronghold = field.sprites[card_tag("P1-SH")]
        sensei = field.sprites[card_tag("P1-extra")]
        assert stronghold.x != sensei.x  # the home row steps them apart, not stacked

    def test_recruited_personality_sits_in_front_of_a_holding(self, loaded):
        field, state = loaded
        holding = L5RCard.of(
            HoldingPrint, id="P1-hold", name="Farm", side=Side.DYNASTY, owner=PlayerId.P1
        )
        personality = L5RCard.of(
            PersonalityPrint, id="P1-pers", name="Bushi", side=Side.DYNASTY, owner=PlayerId.P1
        )
        for card in (holding, personality):
            state.cards_by_id[card.id] = card
            state.battlefield.add(card)
            state.positions[card.id] = UNPLACED_BOARD_POS
        field.reconcile_all()

        # P1 sits at the bottom, so its personalities row is further in (smaller y) than its holdings.
        assert field.sprites[card_tag("P1-pers")].y < field.sprites[card_tag("P1-hold")].y


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
            card = L5RCard.of(CardPrint, id=f"P2-f{i}", name="F", side=Side.FATE, owner=PlayerId.P2)
            state.cards_by_id[card.id] = card
            deck.cards.append(card)
        held = L5RCard.of(CardPrint, id="P2-h", name="Secret", side=Side.FATE, owner=PlayerId.P2)
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
        secret = L5RCard.of(
            CardPrint, id="P2-bf", name="Ambush", side=Side.DYNASTY, owner=PlayerId.P2
        )
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

    def test_an_attached_card_renders_with_its_personality(self, loaded):
        """A unit is the game's own grouping, so the board shows one. Without this the attachment
        is an unplaced non-Personality and files itself with the Holdings, rows away from the
        Personality carrying it."""
        field, _ = loaded
        state = TableState.empty_two_seat()
        hero = L5RCard.of(
            PersonalityPrint,
            id="P1-hero",
            name="Hero",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            force=2,
            chi=3,
        )
        katana = L5RCard.of(
            AttachmentPrint, id="P1-katana", name="Katana", side=Side.FATE, owner=PlayerId.P1
        )
        for card in (hero, katana):
            state.cards_by_id[card.id] = card
            state.battlefield.add(card)
            state.positions[card.id] = UNPLACED_BOARD_POS
        state.units["P1-katana"] = "P1-hero"
        session = EngineSession.start(state, PlayerId.P1)
        field.render_snapshot(session.project(PlayerId.P1).table, PlayerId.P1)

        hero_sprite = field.sprites[card_tag("P1-hero")]
        katana_sprite = field.sprites[card_tag("P1-katana")]
        assert katana_sprite.x == hero_sprite.x
        # Fanned up so its title bar clears the Personality riding it, matching the web board.
        assert katana_sprite.y < hero_sprite.y

        drawn = [entry[0].id for entry in field._unit_draw_order(list(field._render_battlefield()))]
        assert drawn.index("P1-katana") < drawn.index("P1-hero")

    def _unit_board(self, owner, attachments):
        """A board with one Personality owned by ``owner`` and ``attachments`` cards hung on him."""
        state = TableState.empty_two_seat()
        hero = L5RCard.of(
            PersonalityPrint,
            id="hero",
            name="Hero",
            side=Side.DYNASTY,
            owner=owner,
            force=2,
            chi=3,
        )
        cards = [hero] + [
            L5RCard.of(AttachmentPrint, id=card_id, name=card_id, side=Side.FATE, owner=owner)
            for card_id in attachments
        ]
        for card in cards:
            state.cards_by_id[card.id] = card
            state.battlefield.add(card)
            state.positions[card.id] = UNPLACED_BOARD_POS
        for card_id in attachments:
            state.units[card_id] = "hero"
        return state

    def test_a_second_attachment_draws_behind_the_first(self, loaded):
        """The stack fans up, so each card must cover the one it rides: the higher a card sits, the
        further back it draws. Drawn in attach order instead, the second attachment lands on top of
        the first and hides the title the fan exists to expose."""
        field, _ = loaded
        seat = field.seat
        state = self._unit_board(seat, ("katana", "banner"))
        field.render_snapshot(EngineSession.start(state, seat).project(seat).table, seat)

        drawn = [entry[0].id for entry in field._unit_draw_order(list(field._render_battlefield()))]
        assert drawn == ["banner", "katana", "hero"]

        # ...and each one sits a step higher than the card it rides.
        y_of = {card_id: field.sprites[card_tag(card_id)].y for card_id in state.cards_by_id}
        assert y_of["banner"] < y_of["katana"] < y_of["hero"]

    def test_a_unit_grows_down_from_where_its_personality_stood(self, loaded):
        """Both seats' Personalities stand against the divider, so a stack fanning up off the near
        seat's row climbs into the opponent's half. The unit sinks by its own height instead, which
        leaves the top of the stack where the Personality was and keeps it on his own side."""
        field, _ = loaded
        seat = field.seat

        bare = self._unit_board(seat, ())
        field.render_snapshot(EngineSession.start(bare, seat).project(seat).table, seat)
        alone = field.sprites[card_tag("hero")].y

        laden = self._unit_board(seat, ("katana", "banner"))
        field.render_snapshot(EngineSession.start(laden, seat).project(seat).table, seat)

        assert field.sprites[card_tag("hero")].y == alone + 2 * ATTACH_STACK_OFFSET
        assert field.sprites[card_tag("banner")].y == alone  # the stack tops out where he stood

    def test_the_opposing_seats_unit_is_left_where_it_is(self, loaded):
        """Its row sits on the far side of the divider, so fanning up already carries the stack away
        from the near seat rather than across at it."""
        field, _ = loaded
        seat = field.seat
        far = next(other for other in PlayerId if other is not seat)

        bare = self._unit_board(far, ())
        field.render_snapshot(EngineSession.start(bare, seat).project(seat).table, seat)
        alone = field.sprites[card_tag("hero")].y

        laden = self._unit_board(far, ("katana", "banner"))
        field.render_snapshot(EngineSession.start(laden, seat).project(seat).table, seat)

        assert field.sprites[card_tag("hero")].y == alone

    def test_a_fortification_renders_on_the_province_it_defends(self, loaded):
        """A Fortification attaches to a Province slot rather than to a card, so it has no
        Personality to ride and no business in the Holdings row. It fans inboard from the slot,
        because a Province is its seat's outermost row and a stack growing outward leaves the
        board."""
        field, _ = loaded
        seat = field.seat
        state = TableState.empty_two_seat()
        wall = L5RCard.of(
            HoldingPrint,
            id="wall",
            name="Wall",
            side=Side.DYNASTY,
            owner=seat,
            keywords=("Fortification",),
        )
        state.cards_by_id[wall.id] = wall
        state.battlefield.add(wall)
        state.positions[wall.id] = UNPLACED_BOARD_POS
        province = ZoneKey(seat, ZoneRole.PROVINCE, 0)
        for index in range(4):  # empty_two_seat builds no Provinces; the layout needs the row
            state.zones[ZoneKey(seat, ZoneRole.PROVINCE, index)] = ProvinceZone(owner=seat)
        state.province_attachments[wall.id] = province
        field.render_snapshot(EngineSession.start(state, seat).project(seat).table, seat)

        rendered = list(field._render_battlefield())
        assert "wall" not in field._home_positions(rendered, *field._canvas_size())

        w, h = field._canvas_size()
        slot_x, slot_y = province_positions(w, h, 4, seat_at_bottom=True)[0]
        assert field.sprites[card_tag("wall")].x == slot_x
        # Inboard from the near seat's outermost row is toward the divider, so upward.
        assert field.sprites[card_tag("wall")].y == slot_y - ATTACH_STACK_OFFSET

        # ...and tucked under the Province tableau, the way it sits under the card on the table.
        stacking = field.find_all()
        fortification = max(stacking.index(item) for item in field.find_withtag(card_tag("wall")))
        province = min(stacking.index(item) for item in field.find_withtag(zone_tag(province)))
        assert fortification < province

    def _fortified_province(self, field, owner, card_ids):
        """A board where every id in ``card_ids`` is a Fortification on ``owner``'s first Province,
        attached in that order. Always rendered from ``field.seat``, so passing the far seat as
        ``owner`` puts the fan on the far side rather than moving the camera."""
        state = TableState.empty_two_seat()
        province = ZoneKey(owner, ZoneRole.PROVINCE, 0)
        for index in range(4):  # empty_two_seat builds no Provinces; the layout needs the row
            state.zones[ZoneKey(owner, ZoneRole.PROVINCE, index)] = ProvinceZone(owner=owner)
        for card_id in card_ids:
            card = L5RCard.of(
                HoldingPrint,
                id=card_id,
                name=card_id,
                side=Side.DYNASTY,
                owner=owner,
                keywords=("Fortification",),
            )
            state.cards_by_id[card_id] = card
            state.battlefield.add(card)
            state.positions[card_id] = UNPLACED_BOARD_POS
            state.province_attachments[card_id] = province
        viewer = field.seat
        field.render_snapshot(EngineSession.start(state, viewer).project(viewer).table, viewer)
        return province

    def test_a_second_fortification_draws_behind_the_first(self, loaded):
        """The near seat's Provinces fan inboard, which is upward, so each Fortification must cover
        the one above it. Drawn in attach order instead, the second lands on top of the first and
        hides the title the fan exists to expose — the same rule a unit tower follows."""
        field, _ = loaded
        seat = field.seat
        self._fortified_province(field, seat, ("wall", "gate"))

        y_of = {card_id: field.sprites[card_tag(card_id)].y for card_id in ("wall", "gate")}
        assert y_of["gate"] < y_of["wall"]  # the second fans a step further up

        stacking = field.find_all()
        top = {
            card_id: max(stacking.index(item) for item in field.find_withtag(card_tag(card_id)))
            for card_id in ("wall", "gate")
        }
        assert top["gate"] < top["wall"]

    def test_the_far_seats_fan_stacks_the_same_way_it_grows_the_other_direction(self, loaded):
        """Inboard is downward for the far seat, so its stack fans the other way — and the draw
        order does not change with it. What the Province card covers is the nearest Fortification
        either way, so the stack has to ascend toward it from the far end regardless of direction."""
        field, _ = loaded
        far = PlayerId.P2 if field.seat is PlayerId.P1 else PlayerId.P1
        self._fortified_province(field, far, ("wall", "gate"))

        y_of = {card_id: field.sprites[card_tag(card_id)].y for card_id in ("wall", "gate")}
        assert y_of["gate"] > y_of["wall"]  # fanned down instead

        stacking = field.find_all()
        top = {
            card_id: max(stacking.index(item) for item in field.find_withtag(card_tag(card_id)))
            for card_id in ("wall", "gate")
        }
        assert top["gate"] < top["wall"]

    def test_an_attachment_takes_no_column_from_the_holdings_row(self, loaded):
        """The attachment is unplaced and is not a Personality, so the home row would file it with
        the Holdings and shove the real ones sideways to make room for a column nothing draws in."""
        field, _ = loaded
        state = TableState.empty_two_seat()
        hero = L5RCard.of(
            PersonalityPrint,
            id="P1-hero",
            name="Hero",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            force=2,
            chi=3,
        )
        holding = L5RCard.of(
            HoldingPrint, id="P1-mine", name="Mine", side=Side.DYNASTY, owner=PlayerId.P1
        )
        katana = L5RCard.of(
            AttachmentPrint, id="P1-katana", name="Katana", side=Side.FATE, owner=PlayerId.P1
        )
        for card in (hero, holding, katana):
            state.cards_by_id[card.id] = card
            state.battlefield.add(card)
            state.positions[card.id] = UNPLACED_BOARD_POS
        state.units["P1-katana"] = "P1-hero"
        session = EngineSession.start(state, PlayerId.P1)
        field.render_snapshot(session.project(PlayerId.P1).table, PlayerId.P1)

        rendered = list(field._render_battlefield())
        home = field._home_positions(rendered, *field._canvas_size())
        assert "P1-katana" not in home
        assert {"P1-hero", "P1-mine"} <= set(home)

    def _in_play(self, field, *cards):
        """Put ``cards`` on the battlefield, unplaced, and return their home positions."""
        state = TableState.empty_two_seat()
        for card in cards:
            state.cards_by_id[card.id] = card
            state.battlefield.add(card)
            state.positions[card.id] = UNPLACED_BOARD_POS
        session = EngineSession.start(state, PlayerId.P1)
        field.render_snapshot(session.project(PlayerId.P1).table, PlayerId.P1)
        return field._home_positions(list(field._render_battlefield()), *field._canvas_size())

    def test_a_card_with_no_row_stands_in_the_column_at_the_edge(self, loaded):
        """An Event in play is neither a Personality nor a Holding, so it belongs to neither row.
        The column is the leftover, and it stands clear of the rows to the right of both."""
        field, _ = loaded
        hero = L5RCard.of(
            PersonalityPrint,
            id="P1-hero",
            name="Hero",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            force=2,
            chi=3,
        )
        mine = L5RCard.of(
            HoldingPrint, id="P1-mine", name="Mine", side=Side.DYNASTY, owner=PlayerId.P1
        )
        event = L5RCard.of(
            DynastyPrint,
            id="P1-event",
            name="Commanding Favor",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
        )
        home = self._in_play(field, hero, mine, event)

        rows = (home["P1-hero"][0], home["P1-mine"][0])
        assert home["P1-event"][0] - max(rows) >= CARD_W, "a column of its own, not a nudge"

    def test_the_column_stacks_downward_and_overlaps(self, loaded):
        """Several at once — copies of one Edict are the realistic case — share the column, each
        below the last by less than a card's height so the strip of every one stays readable."""
        field, _ = loaded
        events = [
            L5RCard.of(
                DynastyPrint,
                id=f"P1-e{index}",
                name="Edict",
                side=Side.DYNASTY,
                owner=PlayerId.P1,
            )
            for index in range(3)
        ]
        home = self._in_play(field, *events)

        xs = {home[f"P1-e{index}"][0] for index in range(3)}
        ys = [home[f"P1-e{index}"][1] for index in range(3)]
        assert len(xs) == 1, "one column"
        assert ys == sorted(ys), "stacked toward the seat"
        assert 0 < ys[1] - ys[0] < CARD_H, "overlapping, not clear of each other"

    @pytest.mark.parametrize("printed", [SenseiPrint, WindPrint], ids=["sensei", "wind"])
    def test_a_pre_game_permanent_stays_in_the_holdings_row(self, loaded, printed):
        """Neither a Sensei nor a Wind is a Personality or a Holding, so the column's leftover rule
        would swallow both. They start in play beside the stronghold and stay there."""
        field, _ = loaded
        mine = L5RCard.of(
            HoldingPrint, id="P1-mine", name="Mine", side=Side.DYNASTY, owner=PlayerId.P1
        )
        permanent = L5RCard.of(
            printed, id="P1-permanent", name="Permanent", side=Side.FATE, owner=PlayerId.P1
        )
        home = self._in_play(field, mine, permanent)

        assert home["P1-permanent"][1] == home["P1-mine"][1], "same row as the Holdings"

    def _two_copies(self, field, **modified):
        """Two copies of one printed Personality in play, the second given whatever ``modified``
        says. Returns their home positions.

        Each keyword trips exactly one of the reasons a copy leaves the stack, so a test using it
        fails for its own reason rather than for a neighbor's: the Item grants no stat, and the
        counter is one that carries none.

        The modifications land after the session starts, because starting one straightens the board
        and would undo a bow applied before it.
        """
        state = TableState.empty_two_seat()
        for card_id in ("P1-a", "P1-b"):
            copy = L5RCard.of(
                PersonalityPrint,
                id=card_id,
                name="Hero",
                printed_id="hero",
                side=Side.DYNASTY,
                owner=PlayerId.P1,
                force=2,
                chi=3,
            )
            state.cards_by_id[copy.id] = copy
            state.battlefield.add(copy)
            state.positions[copy.id] = UNPLACED_BOARD_POS

        session = EngineSession.start(state, PlayerId.P1)
        table = session.game.table
        if modified.get("attached"):
            charm = L5RCard.of(
                AttachmentPrint, id="P1-charm", name="Charm", side=Side.FATE, owner=PlayerId.P1
            )
            table.cards_by_id[charm.id] = charm
            table.battlefield.add(charm)
            table.units["P1-charm"] = "P1-b"
        if modified.get("counter"):
            table.cards_by_id["P1-b"].adjust_counter("affection", 1)
        if modified.get("bowed"):
            table.cards_by_id["P1-b"].bow()
        if modified.get("note"):
            table.cards_by_id["P1-b"].set_note("dishonored")
        if modified.get("granted"):
            session.game.modifiers.append(
                Modifier("effect", "P1-b", Stat.FORCE, 2, Duration.UNTIL_END_OF_TURN)
            )

        view = session.project(PlayerId.P1)
        field.render_snapshot(view.table, PlayerId.P1, view.stats)
        rendered = list(field._render_battlefield())
        return field._home_positions(rendered, *field._canvas_size())

    @staticmethod
    def _positions(home):
        """The two copies' positions, in the order they were put into play."""
        return home["P1-a"], home["P1-b"]

    def test_two_untouched_copies_share_a_column(self, loaded):
        """Four Rice Fields cost one column rather than four, which is what stacking is for. The
        control for the tests below: without it, a rule that unstacked everything would pass all
        of them."""
        field, _ = loaded

        first, second = self._positions(self._two_copies(field))

        assert second[0] == first[0]
        assert second[1] - first[1] == HOME_STACK_OFFSET  # one steps down behind the other

    def test_a_copy_carrying_an_attachment_takes_a_column_of_its_own(self, loaded):
        """Stacked, the copy behind shows only its top strip, so the Charm hanging off it is drawn
        where nothing reveals it. The Charm grants no stat, so nothing but the attachment itself
        can be what moves the copy out."""
        field, _ = loaded

        first, second = self._positions(self._two_copies(field, attached=True))

        assert second[0] != first[0]

    def test_a_copy_carrying_a_counter_takes_a_column_of_its_own(self, loaded):
        """Affection grants no stat, so the counter is the only thing telling the two apart."""
        field, _ = loaded

        first, second = self._positions(self._two_copies(field, counter=True))

        assert second[0] != first[0]

    def test_a_copy_with_a_modified_stat_keeps_its_place_in_the_stack(self, loaded):
        """Its Force and Chi are stamped in the top corners, which is the strip a stack leaves
        showing — so the number is already legible and moving the copy says nothing new."""
        field, _ = loaded

        first, second = self._positions(self._two_copies(field, granted=True))

        assert second[0] == first[0]
        assert second[1] - first[1] == HOME_STACK_OFFSET

    def test_a_bowed_copy_keeps_its_place_in_the_stack(self, loaded):
        """Bowing is drawn on the card itself and happens every turn, so it must not move anything.
        Giving a bowed copy its own column slid the whole row sideways each time a Holding was
        tapped for gold, and back when it straightened."""
        field, _ = loaded

        first, second = self._positions(self._two_copies(field, bowed=True))

        assert second[0] == first[0]
        assert second[1] - first[1] == HOME_STACK_OFFSET

    def test_a_copy_carrying_a_note_takes_a_column_of_its_own(self, loaded):
        """The note is painted over the card's bottom half, which the stack covers."""
        field, _ = loaded

        first, second = self._positions(self._two_copies(field, note=True))

        assert second[0] != first[0]

    def test_only_the_changed_copy_leaves_the_stack(self, loaded):
        """Three copies and a note on one. Keying the whole printed card out rather than the copy
        would scatter the two that are still interchangeable across columns of their own."""
        field, _ = loaded
        state = TableState.empty_two_seat()
        for card_id in ("P1-a", "P1-b", "P1-c"):
            copy = L5RCard.of(
                PersonalityPrint,
                id=card_id,
                name="Hero",
                printed_id="hero",
                side=Side.DYNASTY,
                owner=PlayerId.P1,
                force=2,
                chi=3,
            )
            state.cards_by_id[copy.id] = copy
            state.battlefield.add(copy)
            state.positions[copy.id] = UNPLACED_BOARD_POS
        session = EngineSession.start(state, PlayerId.P1)
        session.game.table.cards_by_id["P1-b"].set_note("dishonored")
        view = session.project(PlayerId.P1)
        field.render_snapshot(view.table, PlayerId.P1, view.stats)

        home = field._home_positions(list(field._render_battlefield()), *field._canvas_size())

        assert home["P1-a"][0] == home["P1-c"][0]  # still one column between them
        assert home["P1-b"][0] != home["P1-a"][0]

    def test_bowing_a_holding_leaves_the_rest_of_the_row_where_it_was(self, loaded):
        """A producer bows for gold every turn. If that reflows the row, every other Holding jumps
        sideways and back once a turn — which is the whole board moving, to say something the
        card's own rotation already says."""
        field, _ = loaded
        state = TableState.empty_two_seat()
        for card_id, printed_id in (
            ("mine-1", "jade_mine"),
            ("mine-2", "jade_mine"),
            ("farm", "rice_farm"),
        ):
            copy = L5RCard.of(
                HoldingPrint,
                id=card_id,
                name=printed_id,
                printed_id=printed_id,
                side=Side.DYNASTY,
                owner=PlayerId.P1,
                gold_production=2,
            )
            state.cards_by_id[copy.id] = copy
            state.battlefield.add(copy)
            state.positions[copy.id] = UNPLACED_BOARD_POS
        session = EngineSession.start(state, PlayerId.P1)

        def row():
            view = session.project(PlayerId.P1)
            field.render_snapshot(view.table, PlayerId.P1, view.stats)
            return field._home_positions(list(field._render_battlefield()), *field._canvas_size())

        straight = row()
        session.game.table.cards_by_id["mine-1"].bow()

        assert row() == straight

    def test_two_changed_copies_take_a_column_each(self, loaded):
        """Not one column between them. Keying a changed copy by what changed rather than by which
        copy it is would stack the two of them together and hide both."""
        field, _ = loaded
        state = TableState.empty_two_seat()
        for card_id in ("P1-a", "P1-b"):
            copy = L5RCard.of(
                PersonalityPrint,
                id=card_id,
                name="Hero",
                printed_id="hero",
                side=Side.DYNASTY,
                owner=PlayerId.P1,
                force=2,
                chi=3,
            )
            state.cards_by_id[copy.id] = copy
            state.battlefield.add(copy)
            state.positions[copy.id] = UNPLACED_BOARD_POS
        session = EngineSession.start(state, PlayerId.P1)
        for card_id in ("P1-a", "P1-b"):
            session.game.table.cards_by_id[card_id].set_note("dishonored")
        view = session.project(PlayerId.P1)
        field.render_snapshot(view.table, PlayerId.P1, view.stats)

        home = field._home_positions(list(field._render_battlefield()), *field._canvas_size())

        assert home["P1-a"][0] != home["P1-b"][0]

    def test_an_unplaced_hidden_card_still_lands_in_a_home_row(self, loaded):
        """A redacted card renders as a HiddenFace, which carries no print. The home row sorts each
        unplaced card by whether it is a personality, and must not assume it can answer."""
        field, _ = loaded
        state = TableState.empty_two_seat()
        secret = L5RCard.of(
            CardPrint, id="P2-bf", name="Ambush", side=Side.DYNASTY, owner=PlayerId.P2
        )
        secret.turn_face_down()
        state.cards_by_id["P2-bf"] = secret
        state.battlefield.add(secret)
        state.positions["P2-bf"] = UNPLACED_BOARD_POS
        session = EngineSession.start(state, PlayerId.P1)
        field.render_snapshot(session.project(PlayerId.P1).table, PlayerId.P1)

        assert isinstance(field.sprites[card_tag("P2-bf")].card, HiddenFace)

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
        assert field.selection == ("c1", "c2")
        field.toggle_selection("c1")  # clicking again deselects
        assert field.selection == ("c2",)
        field.toggle_selection("nope")  # a non-candidate is ignored, no notification
        assert field.selection == ("c2",)
        assert len(changes) == 3  # one notification per accepted toggle

        field.end_selection()
        assert field.selecting is False
        assert field.selection == ()

    def test_selection_keeps_the_order_the_player_picked(self, loaded):
        field, _ = loaded
        field.begin_selection(["c1", "c2", "c3"])

        field.toggle_selection("c3")
        field.toggle_selection("c1")
        field.toggle_selection("c2")

        assert field.selection == ("c3", "c1", "c2")

    def test_a_deselected_card_reenters_the_selection_at_the_end(self, loaded):
        field, _ = loaded
        field.begin_selection(["c1", "c2"])

        field.toggle_selection("c1")
        field.toggle_selection("c2")
        field.toggle_selection("c1")  # off
        field.toggle_selection("c1")  # and on again

        assert field.selection == ("c2", "c1")

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

    def test_selection_reaches_the_province_visual(self, loaded):
        # The same feed for Provinces, which is where a Cycle or a Dynasty Discard is picked.
        field, _ = loaded
        province_tag = zone_tag(ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0))
        card_id = field.zones[province_tag].cards[-1].id

        field.begin_selection([card_id])
        field.toggle_selection(card_id)
        field.reconcile_all()

        assert card_id in field.zones[province_tag].selected_ids


class TestAllocationSelection:
    def _two_personalities(self, field, state):
        """A second P1 card on the board, so a division has two cards to trade a creation between."""
        extra = L5RCard.of(
            CardPrint, id="P1-extra", name="Bearer", side=Side.DYNASTY, owner=PlayerId.P1
        )
        state.cards_by_id["P1-extra"] = extra
        state.battlefield.add(extra)
        state.positions["P1-extra"] = UNPLACED_BOARD_POS
        field.reconcile_all()
        return "P1-SH", "P1-extra"

    def test_one_chosen_card_takes_every_creation(self, loaded):
        field, _ = loaded
        field.begin_allocation(["a", "b"], 3)

        field.toggle_selection("a")

        # The answer repeats the card once per creation, which is what the engine reads as "three
        # of them go here".
        assert field.selection == ("a", "a", "a")

    def test_choosing_a_second_card_splits_the_creations_between_them(self, loaded):
        field, _ = loaded
        field.begin_allocation(["a", "b"], 4)

        field.toggle_selection("a")
        field.toggle_selection("b")

        assert field.selection == ("a", "a", "b", "b")

    def test_an_arrow_moves_one_creation_across_and_notifies(self, loaded):
        field, _ = loaded
        changes = []
        field.on_selection_changed = lambda: changes.append(1)
        field.begin_allocation(["a", "b"], 4)
        field.toggle_selection("a")
        field.toggle_selection("b")

        field.adjust_allocation("a", 1)

        assert field.selection == ("a", "a", "a", "b")
        assert len(changes) == 3  # two picks and the arrow

    def test_an_arrow_never_empties_a_card_that_is_down_to_one(self, loaded):
        """Carrying nothing is what unchosen means, so the down arrow stops at one; the player
        clicks the card itself to take it out of the division."""
        field, _ = loaded
        field.begin_allocation(["a", "b"], 2)
        field.toggle_selection("a")
        field.toggle_selection("b")

        field.adjust_allocation("a", -1)

        assert field.selection == ("a", "b")

    def test_a_spinner_is_drawn_only_on_the_cards_taking_a_share(self, loaded):
        field, state = loaded
        first, second = self._two_personalities(field, state)
        field.begin_allocation([first, second], 4)

        field.toggle_selection(first)
        field.reconcile_all()

        assert field.find_withtag(f"{ALLOCATION_TAG}&&{card_tag(first)}")
        assert not field.find_withtag(f"{ALLOCATION_TAG}&&{card_tag(second)}")

    def test_the_arrows_are_click_targets_once_there_is_something_to_trade(self, loaded):
        field, state = loaded
        first, second = self._two_personalities(field, state)
        field.begin_allocation([first, second], 4)

        field.toggle_selection(first)
        field.toggle_selection(second)
        field.reconcile_all()

        assert field.find_withtag(allocation_tag(first, 1))
        assert field.find_withtag(allocation_tag(first, -1))

    def test_an_arrow_with_nothing_to_trade_is_drawn_but_inert(self, loaded):
        # A lone chosen card already holds everything, so its arrows do nothing. They stay untagged
        # rather than falling through to the card, which would quietly undo the division.
        field, state = loaded
        first, _ = self._two_personalities(field, state)
        field.begin_allocation([first], 3)

        field.toggle_selection(first)
        field.reconcile_all()

        assert field.find_withtag(ALLOCATION_TAG)  # the count is still shown
        assert not field.find_withtag(allocation_tag(first, 1))

    def test_leaving_the_decision_clears_the_spinners(self, loaded):
        field, state = loaded
        first, _ = self._two_personalities(field, state)
        field.begin_allocation([first], 3)
        field.toggle_selection(first)
        field.reconcile_all()

        field.end_selection()

        assert field.selection == ()
        assert not field.find_withtag(ALLOCATION_TAG)

    def test_an_untouched_division_is_not_yet_a_confirmable_answer(self, loaded):
        """What gates the Confirm button: the presenter offers it only while ``accepts`` holds, and
        a player who has clicked nothing has placed none of the creations."""
        field, _ = loaded
        request = ChooseDistribution(
            PlayerId.P1, ("a", "b"), count=3, resolver="split", source_id="source"
        )
        field.begin_allocation(request.candidates, request.count)
        assert request.accepts(DecisionResponse(field.selection)) is False

        field.toggle_selection("a")

        assert request.accepts(DecisionResponse(field.selection)) is True

    def test_a_later_plain_selection_is_not_still_dividing(self, loaded):
        field, _ = loaded
        field.begin_allocation(["a"], 3)
        field.toggle_selection("a")

        field.begin_selection(["a"])
        field.toggle_selection("a")

        assert field.selection == ("a",)


class TestPaymentSelection:
    def test_undo_last_drops_only_the_most_recent_pick(self, loaded):
        field, _ = loaded
        field.begin_selection(["a", "b", "c"])
        field.toggle_selection("a")
        field.toggle_selection("b")
        field.undo_last_selection()
        assert field.selection == ("a",)

    def test_chosen_producer_previews_as_bowed_during_a_payment(self, loaded):
        field, _ = loaded
        field.begin_selection(["P1-SH"], render_bowed=True)
        field.toggle_selection("P1-SH")
        field.reconcile_all()
        assert field.sprites[card_tag("P1-SH")].bowed_preview is True

    def test_a_plain_selection_does_not_preview_bowed(self, loaded):
        field, _ = loaded
        field.begin_selection(["P1-SH"])  # e.g. a discard selection, not a payment
        field.toggle_selection("P1-SH")
        field.reconcile_all()
        assert field.sprites[card_tag("P1-SH")].bowed_preview is False


class TestDebugSeatFlip:
    def test_flip_renders_from_other_seat(self, loaded):
        field, _ = loaded
        assert field._flipped is False
        field.seat = PlayerId.P2
        field.reconcile_all()
        assert field._flipped is True
        assert card_tag("P2-SH") in field.sprites


class TestDividingCreationsOnTheBoard:
    def test_the_board_answers_a_division_the_engine_paused_for(self, field):
        """End to end over the new decision: the engine pauses to ask how three created Followers
        are divided, the player clicks two Personalities and an arrow, and what the board hands back
        is an answer the engine takes."""
        game = two_seat_game()
        token_template(
            game,
            "suiteirus_podling",
            name="Suiteiru's Podling",
            card_type="Follower",
            keywords=("Oni",),
            force=1,
        )
        put_in_play(game, personality("suiteiru", printed_id="suiteiru_no_oni", force=5, chi=3))
        put_in_play(game, personality("victim", chi=3))
        put_in_play(game, personality("bearer", chi=2))
        session = EngineSession.start(game.table, PlayerId.P1)
        session.act(PlayerId.P1, ActivateAbility("suiteiru"))
        session.submit(PlayerId.P1, DecisionResponse(("victim",)))
        pending = session.game.pending
        field.render_snapshot(session.project(PlayerId.P1).table, PlayerId.P1)

        field.begin_allocation(pending.candidates, pending.count)
        field.toggle_selection("suiteiru")
        field.toggle_selection("bearer")  # an even split of three: two and one
        field.adjust_allocation("bearer", 1)  # the arrow moves one across
        session.submit(PlayerId.P1, DecisionResponse(field.selection))

        game = session.game
        assert len(attachments_of(game, game.table.cards_by_id["bearer"])) == 2
        assert len(attachments_of(game, game.table.cards_by_id["suiteiru"])) == 1

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, UNPLACED_BOARD_POS, ZoneKey, ZoneRole, DeckKey
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.engine.rules.state import Phase
from yasuki_core.engine.rules.decisions import ChoosePayment, DiscardToHandSize, DecisionResponse
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.actions import DynastyDiscard, Pass, Recruit
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.dynasty import DynastyHolding, DynastyPersonality


def _register(state: TableState, card):
    state.cards_by_id[card.id] = card
    return card


def _dealt_table() -> TableState:
    """A two-seat table with a full P1 hand and a fate card to draw, so P1's turn ends in a
    discard."""
    state = TableState.empty_two_seat()
    state.decks[DeckKey(PlayerId.P1, Side.FATE)].cards = [
        _register(state, FateCard(id="P1-fd", name="F", side=Side.FATE, owner=PlayerId.P1))
    ]
    hand = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    for i in range(flow.MAX_HAND_SIZE):
        hand.add(
            _register(state, FateCard(id=f"P1-h{i}", name="H", side=Side.FATE, owner=PlayerId.P1))
        )
    return state


def _to_pending_discard(session: EngineSession) -> None:
    for _ in range(3):  # Action -> Attack -> Dynasty -> end of turn (pauses for discard)
        session.act(PlayerId.P1, Pass())


def test_start_opens_a_playable_first_turn():
    session = EngineSession.start(_dealt_table(), PlayerId.P1, seed=9)
    view = session.project(PlayerId.P1)
    assert view.turn == 1
    assert view.active is PlayerId.P1
    assert view.phase is Phase.ACTION
    assert view.pending is None


def test_legal_actions_offers_pass_to_the_active_seat_only():
    session = EngineSession.start(_dealt_table(), PlayerId.P1)
    assert session.legal_actions(PlayerId.P1) == [Pass()]
    assert session.legal_actions(PlayerId.P2) == []


def _gold_source(state, card_id: str, amount: int, owner=PlayerId.P1) -> DynastyHolding:
    holding = _register(
        state,
        DynastyHolding(
            id=card_id, name="Gold Mine", side=Side.DYNASTY, owner=owner, gold_production=amount
        ),
    )
    state.battlefield.add(holding)
    return holding


def test_gold_is_not_a_free_action_outside_a_payment():
    # Gold is produced only while paying a cost (rules-skeleton §7), so an unbowed producer offers
    # nothing on its own — only Pass is free.
    state = _dealt_table()
    _gold_source(state, "P1-mine", 3)
    session = EngineSession.start(state, PlayerId.P1)
    assert session.legal_actions(PlayerId.P1) == [Pass()]


def _holding_in_province(
    state, card_id: str, *, gold_cost: int, idx: int = 0, keywords=()
) -> DynastyHolding:
    holding = _register(
        state,
        DynastyHolding(
            id=card_id,
            name="Holding",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            gold_cost=gold_cost,
            keywords=keywords,
        ),
    )
    holding.turn_face_up()
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(holding)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, idx)] = province
    return holding


def _in_dynasty(session: EngineSession) -> None:
    session.act(PlayerId.P1, Pass())  # Action -> Attack
    session.act(PlayerId.P1, Pass())  # Attack -> Dynasty
    assert session.project(PlayerId.P1).phase is Phase.DYNASTY


def test_recruit_is_offered_only_in_dynasty_for_an_affordable_face_up_holding():
    state = _dealt_table()
    _gold_source(state, "P1-SH", 8)  # an unbowed producer to pay with
    _holding_in_province(state, "P1-buy", gold_cost=5)
    session = EngineSession.start(state, PlayerId.P1)

    assert Recruit("P1-buy") not in session.legal_actions(PlayerId.P1)  # Action phase
    _in_dynasty(session)
    assert Recruit("P1-buy") in session.legal_actions(PlayerId.P1)


def test_recruit_is_withheld_when_the_seat_cannot_cover_the_cost():
    state = _dealt_table()
    _gold_source(state, "P1-SH", 3)  # only 3 producible
    _holding_in_province(state, "P1-buy", gold_cost=5)
    session = EngineSession.start(state, PlayerId.P1)
    _in_dynasty(session)
    assert Recruit("P1-buy") not in session.legal_actions(PlayerId.P1)


def test_recruit_is_withheld_for_a_face_up_personality():
    # Step 2 buys Holdings only; a revealed Personality in a province is not yet recruitable.
    state = _dealt_table()
    _gold_source(state, "P1-SH", 8)  # plenty to pay with
    person = _register(
        state,
        DynastyPersonality(
            id="P1-person", name="Hero", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=0
        ),
    )
    person.turn_face_up()
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(person)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, PlayerId.P1)
    _in_dynasty(session)

    assert Recruit("P1-person") not in session.legal_actions(PlayerId.P1)


def test_recruit_pays_then_brings_the_holding_into_play_bowed_and_refills():
    state = _dealt_table()
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        _register(
            state, DynastyHolding(id="P1-refill", name="R", side=Side.DYNASTY, owner=PlayerId.P1)
        )
    ]
    _gold_source(state, "P1-SH", 8)
    _holding_in_province(state, "P1-buy", gold_cost=5)
    session = EngineSession.start(state, PlayerId.P1)
    _in_dynasty(session)

    session.act(PlayerId.P1, Recruit("P1-buy"))
    pending = session.project(PlayerId.P1).pending
    assert isinstance(pending, ChoosePayment) and pending.amount == 5
    assert pending.label == "Holding"  # the prompt names the card being bought
    session.submit(PlayerId.P1, DecisionResponse(("P1-SH",)))

    game = session.game
    bought = game.table.cards_by_id["P1-buy"]
    assert bought in game.table.battlefield.cards and bought.bowed
    # It enters unplaced, so the client clusters it into the home row by the stronghold.
    assert game.table.positions["P1-buy"] == UNPLACED_BOARD_POS
    assert game.table.cards_by_id["P1-SH"].bowed  # paying tapped the chosen producer
    assert game.gold[PlayerId.P1] == 3  # 8 produced - 5 spent, excess pools
    refilled = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards
    assert [card.id for card in refilled] == ["P1-refill"] and not refilled[0].face_up
    # The face-down refill is not recruitable until it is revealed next turn.
    assert Recruit("P1-refill") not in session.legal_actions(PlayerId.P1)
    assert game.pending is None and not game.stack


def test_dynasty_discard_is_offered_for_any_face_up_province_card_in_dynasty():
    state = _dealt_table()
    _holding_in_province(state, "P1-junk", gold_cost=9)  # too expensive to recruit
    person = _register(
        state,
        DynastyPersonality(
            id="P1-person", name="Hero", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=0
        ),
    )
    person.turn_face_up()
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(person)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 1)] = province
    session = EngineSession.start(state, PlayerId.P1)

    assert DynastyDiscard("P1-junk") not in session.legal_actions(PlayerId.P1)  # Action phase
    _in_dynasty(session)
    actions = session.legal_actions(PlayerId.P1)
    assert (
        DynastyDiscard("P1-junk") in actions
    )  # a Holding too expensive to recruit is still discardable
    assert DynastyDiscard("P1-person") in actions  # a Personality is discardable, not recruitable
    assert Recruit("P1-person") not in actions


def test_dynasty_discard_moves_the_card_to_the_discard_and_refills():
    state = _dealt_table()
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        _register(
            state, DynastyHolding(id="P1-refill", name="R", side=Side.DYNASTY, owner=PlayerId.P1)
        )
    ]
    _holding_in_province(state, "P1-junk", gold_cost=9)
    session = EngineSession.start(state, PlayerId.P1)
    _in_dynasty(session)

    session.act(PlayerId.P1, DynastyDiscard("P1-junk"))

    game = session.game
    discard = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)].cards
    assert game.table.cards_by_id["P1-junk"] in discard
    refilled = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards
    assert [card.id for card in refilled] == ["P1-refill"] and not refilled[0].face_up
    assert game.pending is None and not game.stack  # no cost, resolves at once


def test_dynasty_discard_survives_a_replay():
    state = _dealt_table()
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        _register(
            state, DynastyHolding(id="P1-refill", name="R", side=Side.DYNASTY, owner=PlayerId.P1)
        )
    ]
    _holding_in_province(state, "P1-junk", gold_cost=9)
    session = EngineSession.start(state, PlayerId.P1)
    _in_dynasty(session)
    session.act(PlayerId.P1, DynastyDiscard("P1-junk"))

    replayed = session.log.replay()
    discard = replayed.table.zones[ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)].cards
    assert any(card.id == "P1-junk" for card in discard)


def test_jade_works_funds_and_pays_a_jade_recruit_at_its_premium_rate():
    state = _dealt_table()
    works = _register(
        state,
        DynastyHolding(
            id="P1-jadeworks",
            printed_id="jade_works",
            name="Jade Works",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            gold_production=3,
        ),
    )
    state.battlefield.add(works)
    _holding_in_province(state, "P1-jade", gold_cost=5, keywords=("Jade",))
    session = EngineSession.start(state, PlayerId.P1)
    _in_dynasty(session)

    # Affordability counts Jade Works as 5 toward a Jade card, so the 5-cost recruit is offered.
    assert Recruit("P1-jade") in session.legal_actions(PlayerId.P1)

    session.act(PlayerId.P1, Recruit("P1-jade"))
    pending = session.project(PlayerId.P1).pending
    assert isinstance(pending, ChoosePayment)
    assert dict(pending.produced)["P1-jadeworks"] == 5  # the premium 5, not the printed 3

    session.submit(PlayerId.P1, DecisionResponse(("P1-jadeworks",)))
    game = session.game
    assert game.table.cards_by_id["P1-jade"] in game.table.battlefield.cards  # recruited
    assert game.gold[PlayerId.P1] == 0  # produced 5, spent 5 — application matched the offer


def test_cancel_backs_out_of_a_recruit_payment_committing_nothing():
    state = _dealt_table()
    _gold_source(state, "P1-SH", 8)
    holding = _holding_in_province(state, "P1-buy", gold_cost=5)
    session = EngineSession.start(state, PlayerId.P1)
    _in_dynasty(session)

    session.act(PlayerId.P1, Recruit("P1-buy"))
    assert isinstance(session.game.pending, ChoosePayment)

    session.cancel(PlayerId.P1)

    game = session.game
    assert game.pending is None and not game.stack
    # Nothing was committed: the holding sits face-up in its province, no gold spent, producer ready.
    province = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards
    assert holding in province and holding.face_up
    assert holding not in game.table.battlefield.cards
    assert game.gold[PlayerId.P1] == 0
    assert not game.table.cards_by_id["P1-SH"].bowed
    # The holding can be recruited again, and the logged cancel replays to the same live state.
    assert Recruit("P1-buy") in session.legal_actions(PlayerId.P1)
    replayed = session.log.replay()
    assert replayed.pending is None and not replayed.stack


def test_cancel_rejects_a_seat_that_is_not_being_asked():
    state = _dealt_table()
    _gold_source(state, "P1-SH", 8)
    _holding_in_province(state, "P1-buy", gold_cost=5)
    session = EngineSession.start(state, PlayerId.P1)
    _in_dynasty(session)
    session.act(PlayerId.P1, Recruit("P1-buy"))

    with pytest.raises(ValueError):
        session.cancel(PlayerId.P2)


def test_cancel_of_a_forced_end_of_turn_discard_is_rejected():
    session = EngineSession.start(_dealt_table(), PlayerId.P1)
    _to_pending_discard(session)
    assert isinstance(session.game.pending, DiscardToHandSize)

    with pytest.raises(ValueError):
        session.cancel(PlayerId.P1)
    assert isinstance(session.game.pending, DiscardToHandSize)  # still owed


def test_act_pass_moves_the_phase_and_rejects_an_illegal_actor():
    session = EngineSession.start(_dealt_table(), PlayerId.P1)
    session.act(PlayerId.P1, Pass())
    assert session.project(PlayerId.P1).phase is Phase.ATTACK
    # The inactive seat has no legal action, so acting raises.
    with pytest.raises(ValueError):
        session.act(PlayerId.P2, Pass())


def test_pending_decision_blocks_actions_and_reaches_its_answerer():
    session = EngineSession.start(_dealt_table(), PlayerId.P1)
    _to_pending_discard(session)

    # A pending decision suspends free actions for everyone.
    assert session.legal_actions(PlayerId.P1) == []
    # Only the answerer sees the request.
    pending = session.project(PlayerId.P1).pending
    assert isinstance(pending, DiscardToHandSize) and pending.seat is PlayerId.P1
    assert pending.count == 1
    assert session.project(PlayerId.P2).pending is None
    # Only the answerer may answer it.
    with pytest.raises(ValueError):
        session.submit(PlayerId.P2, DecisionResponse(("P1-h0",)))


def test_submit_resolves_the_decision_and_passes_the_turn():
    session = EngineSession.start(_dealt_table(), PlayerId.P1)
    _to_pending_discard(session)
    victim = session.project(PlayerId.P1).pending
    assert isinstance(victim, DiscardToHandSize)

    discard = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards[0].id
    session.submit(PlayerId.P1, DecisionResponse((discard,)))

    assert not session.game.awaiting_decision
    assert session.project(PlayerId.P2).active is PlayerId.P2  # turn passed


def test_submit_without_a_pending_decision_raises():
    session = EngineSession.start(_dealt_table(), PlayerId.P1)
    with pytest.raises(RuntimeError):
        session.submit(PlayerId.P1, DecisionResponse(()))


def test_session_log_replays_to_the_live_game():
    session = EngineSession.start(_dealt_table(), PlayerId.P1)
    _to_pending_discard(session)
    discard = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards[0].id
    session.submit(PlayerId.P1, DecisionResponse((discard,)))

    assert replay(session.log) == session.game


def test_undo_last_reverses_a_dynasty_discard_and_cannot_repeat():
    state = _dealt_table()
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        _register(
            state, DynastyHolding(id="P1-refill", name="R", side=Side.DYNASTY, owner=PlayerId.P1)
        )
    ]
    _holding_in_province(state, "P1-junk", gold_cost=9)
    session = EngineSession.start(state, PlayerId.P1)
    _in_dynasty(session)
    session.act(PlayerId.P1, DynastyDiscard("P1-junk"))

    assert session.undo_last(PlayerId.P1) is True

    province = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards
    assert [card.id for card in province] == ["P1-junk"] and province[0].face_up
    assert session.undo_last(PlayerId.P1) is False  # the discard is gone from the tape


def test_undo_last_is_a_noop_without_a_trailing_discard():
    state = _dealt_table()
    _holding_in_province(state, "P1-junk", gold_cost=9)
    session = EngineSession.start(state, PlayerId.P1)
    _in_dynasty(session)  # the last logged action is a Pass, not a discard

    assert session.undo_last(PlayerId.P1) is False


def test_undo_last_does_not_reverse_a_recruit():
    state = _dealt_table()
    _gold_source(state, "P1-SH", 8)
    _holding_in_province(state, "P1-buy", gold_cost=5)
    session = EngineSession.start(state, PlayerId.P1)
    _in_dynasty(session)
    session.act(PlayerId.P1, Recruit("P1-buy"))
    session.submit(PlayerId.P1, DecisionResponse(("P1-SH",)))  # pay -> the holding enters play

    assert session.undo_last(PlayerId.P1) is False  # undo only reverses a Dynasty Discard
    assert session.game.table.cards_by_id["P1-buy"] in session.game.table.battlefield.cards

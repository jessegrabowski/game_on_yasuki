import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, UNPLACED_BOARD_POS, ZoneKey, ZoneRole, DeckKey
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.engine.rules.state import Phase
from yasuki_core.engine.rules.decisions import ChoosePayment, DiscardToHandSize, DecisionResponse
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.actions import Pass, Recruit
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


def _holding_in_province(state, card_id: str, *, gold_cost: int, idx: int = 0) -> DynastyHolding:
    holding = _register(
        state,
        DynastyHolding(
            id=card_id, name="Holding", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=gold_cost
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

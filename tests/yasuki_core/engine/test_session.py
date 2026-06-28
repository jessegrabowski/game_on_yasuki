import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.engine.rules.state import Phase
from yasuki_core.engine.rules.decisions import DiscardToHandSize, DecisionResponse
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.actions import Pass, ProduceGold
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.dynasty import DynastyHolding


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


def test_legal_actions_offers_produce_gold_for_each_unbowed_gold_source():
    state = _dealt_table()
    _gold_source(state, "P1-mine", 3)
    _gold_source(state, "P1-farm", 2)
    _gold_source(state, "P2-mine", 4, owner=PlayerId.P2)  # the opponent's source is not offered
    session = EngineSession.start(state, PlayerId.P1)

    offered = session.legal_actions(PlayerId.P1)
    assert ProduceGold("P1-mine", 3) in offered
    assert ProduceGold("P1-farm", 2) in offered
    assert ProduceGold("P2-mine", 4) not in offered


def test_producing_gold_fills_the_pool_and_bows_the_source():
    state = _dealt_table()
    _gold_source(state, "P1-mine", 3)
    session = EngineSession.start(state, PlayerId.P1)

    session.act(PlayerId.P1, ProduceGold("P1-mine", 3))

    assert session.project(PlayerId.P1).gold[PlayerId.P1] == 3
    # A bowed source can no longer produce, so the action drops off the legal list.
    assert ProduceGold("P1-mine", 3) not in session.legal_actions(PlayerId.P1)


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

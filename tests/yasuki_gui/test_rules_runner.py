from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.engine.rules.state import Phase
from yasuki_core.engine.rules.decisions import DiscardToHandSize
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_gui.rules_runner import GameRunner


def _register(state, card):
    state.cards_by_id[card.id] = card
    return card


def _dealt_table(p1_hand: int) -> TableState:
    state = TableState.empty_two_seat()
    for seat in PlayerId:
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            _register(state, FateCard(id=f"{seat.name}-fd", name="F", side=Side.FATE, owner=seat))
        ]
    hand = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    for i in range(p1_hand):
        hand.add(
            _register(state, FateCard(id=f"P1-h{i}", name="H", side=Side.FATE, owner=PlayerId.P1))
        )
    return state


def _runner(p1_hand: int = 0) -> GameRunner:
    session = EngineSession.start(_dealt_table(p1_hand), PlayerId.P1, seed=3)
    return GameRunner(session, PlayerId.P1)


def test_advance_walks_the_human_through_the_phases():
    runner = _runner()
    assert runner.view().phase is Phase.ACTION
    runner.advance()
    assert runner.view().phase is Phase.ATTACK
    runner.advance()
    assert runner.view().phase is Phase.DYNASTY


def test_ending_a_quiet_turn_auto_runs_the_opponent_back_to_the_human():
    runner = _runner(p1_hand=0)  # no discard for either seat
    for _ in range(3):  # Action -> Attack -> Dynasty -> end of P1's turn
        runner.advance()

    view = runner.view()
    # P2's empty turn ran automatically; it is the human's turn again on turn 3.
    assert view.active is PlayerId.P1
    assert view.turn == 3
    assert view.phase is Phase.ACTION
    assert runner.pending_discard is None


def test_human_discard_is_left_pending_then_resolved():
    runner = _runner(p1_hand=flow.MAX_HAND_SIZE)  # 8 held + 1 drawn = 9 at end of turn
    for _ in range(3):
        runner.advance()

    pending = runner.pending_discard
    assert pending == DiscardToHandSize(PlayerId.P1, count=1)
    assert runner.view().turn == 1  # turn not passed while the discard is owed

    # Advancing is blocked until the discard is answered.
    runner.advance()
    assert runner.pending_discard is not None

    hand = runner.session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards
    runner.resolve_discard([hand[0].id])

    assert runner.pending_discard is None
    assert runner.view().active is PlayerId.P1 and runner.view().turn == 3


def test_runner_inputs_stay_replayable():
    runner = _runner(p1_hand=flow.MAX_HAND_SIZE)
    for _ in range(3):
        runner.advance()
    hand = runner.session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards
    runner.resolve_discard([hand[0].id])

    assert replay(runner.session.log) == runner.session.game

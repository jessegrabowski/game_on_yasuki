from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.engine.rules.state import Phase
from yasuki_core.engine.rules.decisions import DiscardToHandSize
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.actions import Pass
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.dynasty import DynastyHolding
from yasuki_core.game_pieces.pregame import StrongholdCard
from yasuki_gui.rules_runner import GameRunner

PASS = Pass()


def _face_up_holding_in_province(state, card_id, gold_cost):
    holding = _register(
        state,
        DynastyHolding(
            id=card_id, name="H", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=gold_cost
        ),
    )
    holding.turn_face_up()
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(holding)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = province
    return holding


def _to_dynasty(runner):
    runner.act(PASS)  # Action -> Attack
    runner.act(PASS)  # Attack -> Dynasty


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


def test_passing_walks_the_human_through_the_phases():
    runner = _runner()
    assert runner.view().phase is Phase.ACTION
    runner.act(PASS)
    assert runner.view().phase is Phase.ATTACK
    runner.act(PASS)
    assert runner.view().phase is Phase.DYNASTY


def test_passing_through_a_quiet_turn_hands_off_then_back():
    runner = _runner(p1_hand=0)  # no discard for either seat
    for _ in range(3):  # Action -> Attack -> Dynasty -> end of P1's turn
        runner.act(PASS)

    assert runner.is_opponent_turn  # control rests with the opponent, not yet run
    runner.run_opponent()

    view = runner.view()
    assert view.active is PlayerId.P1 and view.turn == 3 and view.phase is Phase.ACTION
    assert not runner.is_opponent_turn


def test_human_discard_is_left_pending_then_resolved():
    runner = _runner(p1_hand=flow.MAX_HAND_SIZE)  # 8 held + 1 drawn = 9 at end of turn
    for _ in range(3):
        runner.act(PASS)

    pending = runner.pending
    assert isinstance(pending, DiscardToHandSize) and pending.count == 1
    assert not runner.is_opponent_turn  # still the human's turn while the discard is owed
    assert runner.legal_actions() == []  # no free action offered until it is answered

    hand = runner.session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards
    runner.submit([hand[0].id])

    assert runner.pending is None
    assert runner.is_opponent_turn  # the turn has passed; the caller now runs the opponent
    runner.run_opponent()
    assert runner.view().active is PlayerId.P1 and runner.view().turn == 3


def test_opponents_overfull_turn_auto_discards_without_prompting():
    state = TableState.empty_two_seat()
    for seat in PlayerId:
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            _register(state, FateCard(id=f"{seat.name}-fd", name="F", side=Side.FATE, owner=seat))
        ]
    p2_hand = state.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)]
    for i in range(flow.MAX_HAND_SIZE):
        p2_hand.add(
            _register(state, FateCard(id=f"P2-h{i}", name="H", side=Side.FATE, owner=PlayerId.P2))
        )
    runner = GameRunner(EngineSession.start(state, PlayerId.P1), PlayerId.P1)

    for _ in range(3):  # end P1's quiet turn
        runner.act(PASS)
    runner.run_opponent()  # P2's overfull turn auto-passes and auto-discards

    assert runner.view().active is PlayerId.P1 and runner.view().turn == 3
    assert runner.pending is None  # the opponent's discard resolved without a prompt
    p2_after = runner.session.game.table.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)].cards
    assert len(p2_after) == flow.MAX_HAND_SIZE  # 8 held + 1 drawn = 9, auto-trimmed to 8


def test_runner_inputs_stay_replayable():
    runner = _runner(p1_hand=flow.MAX_HAND_SIZE)
    for _ in range(3):
        runner.act(PASS)
    hand = runner.session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards
    runner.submit([hand[0].id])
    runner.run_opponent()

    assert replay(runner.session.log) == runner.session.game


def test_province_menu_offers_recruit_with_cost_and_dynasty_discard():
    state = _dealt_table(0)
    state.battlefield.add(
        _register(
            state,
            StrongholdCard(
                id="P1-SH", name="SH", side=Side.STRONGHOLD, owner=PlayerId.P1, gold_production=8
            ),
        )
    )
    _face_up_holding_in_province(state, "P1-buy", gold_cost=5)
    runner = GameRunner(EngineSession.start(state, PlayerId.P1, seed=3), PlayerId.P1)
    _to_dynasty(runner)

    labels = [label for label, _ in runner.province_menu("P1-buy")]
    assert labels == ["Recruit: Pay 5 gold", "Repeatable Dynasty: Discard from province"]


def test_province_menu_drops_recruit_when_it_is_unaffordable():
    state = _dealt_table(0)
    _face_up_holding_in_province(state, "P1-buy", gold_cost=9)  # no producer to pay with
    runner = GameRunner(EngineSession.start(state, PlayerId.P1, seed=3), PlayerId.P1)
    _to_dynasty(runner)

    labels = [label for label, _ in runner.province_menu("P1-buy")]
    assert labels == ["Repeatable Dynasty: Discard from province"]

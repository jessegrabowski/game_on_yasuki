import json

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.engine.snapshot import InitialRecord
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.rules.actions import Pass, Recruit
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.log import (
    GameLog,
    Act,
    Answer,
    Cancel,
    build_game,
    act_and_log,
    submit_and_log,
    cancel_and_log,
    replay,
    game_log_to_dict,
    game_log_from_dict,
    _decode_action,
)
from yasuki_core.game_pieces.dynasty import DynastyHolding


def _register(state: TableState, card):
    state.cards_by_id[card.id] = card
    return card


def _dealt_table() -> TableState:
    """A two-seat table where P1 holds a full hand and has a fate card to draw, forcing an
    end-of-turn discard."""
    state = TableState.empty_two_seat()
    for seat in PlayerId:
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            _register(state, FateCard(id=f"{seat.name}-fd", name="F", side=Side.FATE, owner=seat))
        ]
    hand = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    for i in range(flow.MAX_HAND_SIZE):
        hand.add(
            _register(state, FateCard(id=f"P1-h{i}", name="H", side=Side.FATE, owner=PlayerId.P1))
        )
    return state


def _played_game_and_log() -> tuple:
    """Play P1's full turn — three advances into the end-of-turn discard, then the discard —
    recording every input to the log."""
    log = GameLog(initial=InitialRecord.from_state(_dealt_table()), first_player=PlayerId.P1)
    game = build_game(log)
    act_and_log(game, log, Pass())  # Action -> Attack
    act_and_log(game, log, Pass())  # Attack -> Dynasty
    act_and_log(game, log, Pass())  # Dynasty -> end of turn, pauses for discard
    victim = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards[0].id
    submit_and_log(game, log, DecisionResponse((victim,)))
    return game, log


def test_replay_reproduces_the_played_game():
    game, log = _played_game_and_log()
    assert replay(log) == game


def test_log_records_each_input_in_order():
    _, log = _played_game_and_log()
    assert [type(entry) for entry in log.entries] == [Act, Act, Act, Answer]
    assert all(entry.seat is PlayerId.P1 for entry in log.entries)


def test_recruit_action_and_its_payment_replay_and_round_trip():
    state = _dealt_table()
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        _register(
            state, DynastyHolding(id="P1-refill", name="R", side=Side.DYNASTY, owner=PlayerId.P1)
        )
    ]
    state.battlefield.add(
        _register(
            state,
            DynastyHolding(
                id="P1-SH", name="SH", side=Side.DYNASTY, owner=PlayerId.P1, gold_production=8
            ),
        )
    )
    holding = _register(
        state,
        DynastyHolding(id="P1-buy", name="Buy", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=5),
    )
    holding.turn_face_up()
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(holding)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = province

    log = GameLog(initial=InitialRecord.from_state(state), first_player=PlayerId.P1)
    game = build_game(log)
    act_and_log(game, log, Pass())  # Action -> Attack
    act_and_log(game, log, Pass())  # Attack -> Dynasty
    act_and_log(game, log, Recruit("P1-buy"))  # pauses for payment
    submit_and_log(game, log, DecisionResponse(("P1-SH",)))

    assert game.table.cards_by_id["P1-buy"] in game.table.battlefield.cards
    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(log))))
    assert restored.replay() == game


def test_cancelled_recruit_payment_replays_and_round_trips():
    state = _dealt_table()
    state.battlefield.add(
        _register(
            state,
            DynastyHolding(
                id="P1-SH", name="SH", side=Side.DYNASTY, owner=PlayerId.P1, gold_production=8
            ),
        )
    )
    holding = _register(
        state,
        DynastyHolding(id="P1-buy", name="Buy", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=5),
    )
    holding.turn_face_up()
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(holding)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = province

    log = GameLog(initial=InitialRecord.from_state(state), first_player=PlayerId.P1)
    game = build_game(log)
    act_and_log(game, log, Pass())  # Action -> Attack
    act_and_log(game, log, Pass())  # Attack -> Dynasty
    act_and_log(game, log, Recruit("P1-buy"))  # pauses for payment
    cancel_and_log(game, log)  # backs out

    assert log.entries[-1] == Cancel(PlayerId.P1)
    assert game.pending is None and game.table.cards_by_id["P1-buy"] in province.cards
    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(log))))
    assert restored.replay() == game


def test_serialization_round_trips_then_replays():
    game, log = _played_game_and_log()
    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(log))))
    assert restored.entries == log.entries
    assert restored.replay() == game


def test_submit_and_log_does_not_record_a_rejected_answer():
    log = GameLog(initial=InitialRecord.from_state(_dealt_table()), first_player=PlayerId.P1)
    game = build_game(log)
    for _ in range(3):
        act_and_log(game, log, Pass())
    entries_before = len(log.entries)

    with pytest.raises(ValueError):  # must discard exactly one card
        submit_and_log(game, log, DecisionResponse(()))

    assert len(log.entries) == entries_before
    assert game.awaiting_decision


def test_replay_rejects_a_desynced_tape():
    log = GameLog(
        initial=InitialRecord.from_state(_dealt_table()),
        first_player=PlayerId.P1,
        entries=[Act(PlayerId.P2, Pass())],  # P1 starts, so an opening P2 act is impossible
    )
    with pytest.raises(ValueError, match="out of step"):
        replay(log)


def test_decode_action_rejects_an_unknown_kind():
    # A malformed log must fail loudly, not silently mis-decode as some default action.
    with pytest.raises(ValueError):
        _decode_action({"kind": "bogus"})

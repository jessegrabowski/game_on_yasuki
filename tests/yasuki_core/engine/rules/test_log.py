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
from yasuki_core.game_pieces.dynasty import DynastyHolding, DynastyPersonality
from yasuki_core.game_pieces.pregame import StrongholdCard


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


def _place_in_province(state: TableState, card):
    """Register ``card`` and set it face-up as the sole card of P1's first province."""
    _register(state, card)
    card.turn_face_up()
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(card)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = province
    return card


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
    _place_in_province(
        state,
        DynastyHolding(id="P1-buy", name="Buy", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=5),
    )

    log = GameLog(initial=InitialRecord.from_state(state), first_player=PlayerId.P1)
    game = build_game(log)
    act_and_log(game, log, Pass())  # Action -> Attack
    act_and_log(game, log, Pass())  # Attack -> Dynasty
    act_and_log(game, log, Recruit("P1-buy"))  # pauses for payment
    submit_and_log(game, log, DecisionResponse(("P1-SH",)))

    assert game.table.cards_by_id["P1-buy"] in game.table.battlefield.cards
    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(log))))
    assert restored.replay() == game


def test_proclaimed_recruit_replays_and_round_trips():
    # The proclaim flag must survive the codec, or a replay would drop the honor gain.
    state = _dealt_table()
    state.battlefield.add(
        _register(
            state,
            StrongholdCard(
                id="P1-strong", name="Keep", side=Side.STRONGHOLD, owner=PlayerId.P1, clan="Crab"
            ),
        )
    )
    state.battlefield.add(
        _register(
            state,
            DynastyHolding(
                id="P1-SH", name="SH", side=Side.DYNASTY, owner=PlayerId.P1, gold_production=8
            ),
        )
    )
    _place_in_province(
        state,
        DynastyPersonality(
            id="P1-person",
            name="Hero",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            gold_cost=5,
            clan="Crab",
            personal_honor=2,
        ),
    )

    log = GameLog(initial=InitialRecord.from_state(state), first_player=PlayerId.P1)
    game = build_game(log)
    act_and_log(game, log, Pass())  # Action -> Attack
    act_and_log(game, log, Pass())  # Attack -> Dynasty
    act_and_log(game, log, Recruit("P1-person", proclaim=True))  # pauses for payment
    submit_and_log(game, log, DecisionResponse(("P1-SH",)))

    assert game.table.seats[PlayerId.P1].honor == 2
    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(log))))
    assert restored.replay() == game


def test_boosted_payment_round_trips_through_the_codec():
    # The payment answer carries which producers were boosted; that must survive JSON encode/decode.
    state = _dealt_table()
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        _register(
            state, DynastyHolding(id="P1-refill", name="R", side=Side.DYNASTY, owner=PlayerId.P1)
        )
    ]
    outlying = _register(
        state,
        DynastyHolding(
            id="P1-of",
            name="Outlying Farms",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            printed_id="outlying_farms",
            keywords=("Farm",),
            gold_production=2,
        ),
    )
    state.battlefield.add(outlying)
    _place_in_province(
        state,
        DynastyHolding(id="P1-buy", name="Buy", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=4),
    )

    log = GameLog(initial=InitialRecord.from_state(state), first_player=PlayerId.P1)
    game = build_game(log)
    act_and_log(game, log, Pass())  # Action -> Attack
    act_and_log(game, log, Pass())  # Attack -> Dynasty
    act_and_log(game, log, Recruit("P1-buy"))
    submit_and_log(
        game, log, DecisionResponse(("P1-of",), ("P1-of",))
    )  # bow Outlying Farms boosted

    assert outlying not in game.table.battlefield.cards  # destroyed after bowing boosted
    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(log))))
    assert restored.replay() == game


def test_triggered_choice_replays_and_round_trips():
    # Recruiting a Wheat Farm fires its EnteredPlay trigger, which pauses to choose other Farms to
    # give a Wealth token — the recruit -> pay -> choose -> resume chain must survive replay.
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
    state.battlefield.add(
        _register(
            state,
            DynastyHolding(
                id="P1-other",
                name="Other Farm",
                side=Side.DYNASTY,
                owner=PlayerId.P1,
                keywords=("Farm",),
                gold_production=2,
            ),
        )
    )
    _place_in_province(
        state,
        DynastyHolding(
            id="P1-wheat",
            name="Wheat Farm",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            printed_id="wheat_farm",
            keywords=("Farm",),
            gold_cost=3,
        ),
    )

    log = GameLog(initial=InitialRecord.from_state(state), first_player=PlayerId.P1)
    game = build_game(log)
    act_and_log(game, log, Pass())  # Action -> Attack
    act_and_log(game, log, Pass())  # Attack -> Dynasty
    act_and_log(game, log, Recruit("P1-wheat"))  # pauses for payment
    submit_and_log(game, log, DecisionResponse(("P1-SH",)))  # pays, then pauses for the choice
    submit_and_log(game, log, DecisionResponse(("P1-other",)))  # give the other Farm a token

    assert game.pending is None and game.stack == []
    assert game.table.cards_by_id["P1-other"].counters == {"wealth": 1}
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
    _place_in_province(
        state,
        DynastyHolding(id="P1-buy", name="Buy", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=5),
    )

    log = GameLog(initial=InitialRecord.from_state(state), first_player=PlayerId.P1)
    game = build_game(log)
    act_and_log(game, log, Pass())  # Action -> Attack
    act_and_log(game, log, Pass())  # Attack -> Dynasty
    act_and_log(game, log, Recruit("P1-buy"))  # pauses for payment
    cancel_and_log(game, log)  # backs out

    assert log.entries[-1] == Cancel(PlayerId.P1)
    province = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)]
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

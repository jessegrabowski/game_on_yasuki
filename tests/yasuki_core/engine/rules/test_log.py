import json
import typing

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import HoldingPrint, PersonalityPrint, StrongholdPrint
from yasuki_core.engine.snapshot import InitialRecord
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.rules.actions import (
    Action,
    ActivateAbility,
    Cycle,
    DynastyDiscard,
    Equip,
    Inheritance,
    KharmicDraw,
    KharmicRefill,
    Legacy,
    Pass,
    Recruit,
)
from yasuki_core.engine.rules.decisions import DecisionResponse
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

from tests.yasuki_core.engine.builders import put_in_play, register

from tests.yasuki_core.engine.builders import dealt_table


def _place_in_province(state: TableState, card):
    """Register ``card`` and set it face-up as the sole card of P1's first province."""
    register(state, card)
    card.turn_face_up()
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(card)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = province
    return card


def _played_game_and_log() -> tuple:
    """Play P1's full turn into the end-of-turn discard, then the discard, recording every input.

    Four passes rather than three: the Action phase gives P2 an Open window it has to decline.
    """
    log = GameLog(initial=InitialRecord.from_state(dealt_table()), first_player=PlayerId.P1)
    game = build_game(log)
    act_and_log(game, log, Pass())  # P1 declines the Action phase
    act_and_log(game, log, Pass())  # P2 declines its Open window: Action -> Battle
    act_and_log(game, log, Pass())  # Battle -> Dynasty
    act_and_log(game, log, Pass())  # Dynasty -> end of turn, pauses for discard
    victim = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards[0].id
    submit_and_log(game, log, DecisionResponse((victim,)))
    return game, log


def test_replay_reproduces_the_played_game():
    game, log = _played_game_and_log()
    assert replay(log) == game


def test_log_records_each_input_in_order():
    _, log = _played_game_and_log()
    assert [type(entry) for entry in log.entries] == [Act, Act, Act, Act, Answer]
    assert [entry.seat for entry in log.entries] == [
        PlayerId.P1,  # declines the Action phase
        PlayerId.P2,  # declines its Open window
        PlayerId.P1,  # Battle
        PlayerId.P1,  # Dynasty
        PlayerId.P1,  # the end-of-turn discard
    ]


def test_recruit_action_and_its_payment_replay_and_round_trip():
    state = dealt_table()
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        register(
            state,
            L5RCard.of(
                HoldingPrint, id="P1-refill", name="R", side=Side.DYNASTY, owner=PlayerId.P1
            ),
        )
    ]
    put_in_play(
        state,
        L5RCard.of(
            HoldingPrint,
            id="P1-SH",
            name="SH",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            gold_production=8,
        ),
    )
    _place_in_province(
        state,
        L5RCard.of(
            HoldingPrint, id="P1-buy", name="Buy", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=5
        ),
    )

    log = GameLog(initial=InitialRecord.from_state(state), first_player=PlayerId.P1)
    game = build_game(log)
    act_and_log(game, log, Pass())  # P1 declines the Action phase
    act_and_log(game, log, Pass())  # P2 declines its Open window: Action -> Battle
    act_and_log(game, log, Pass())  # Battle -> Dynasty
    act_and_log(game, log, Recruit("P1-buy"))  # pauses for payment
    submit_and_log(game, log, DecisionResponse(("P1-SH",)))

    assert game.table.cards_by_id["P1-buy"] in game.table.battlefield.cards
    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(log))))
    assert restored.replay() == game


def test_proclaimed_recruit_replays_and_round_trips():
    # The proclaim flag must survive the codec, or a replay would drop the honor gain.
    state = dealt_table()
    put_in_play(
        state,
        L5RCard.of(
            StrongholdPrint,
            id="P1-strong",
            name="Keep",
            side=Side.STRONGHOLD,
            owner=PlayerId.P1,
            clan="Crab",
        ),
    )
    put_in_play(
        state,
        L5RCard.of(
            HoldingPrint,
            id="P1-SH",
            name="SH",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            gold_production=8,
        ),
    )
    _place_in_province(
        state,
        L5RCard.of(
            PersonalityPrint,
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
    act_and_log(game, log, Pass())  # P1 declines the Action phase
    act_and_log(game, log, Pass())  # P2 declines its Open window: Action -> Battle
    act_and_log(game, log, Pass())  # Battle -> Dynasty
    act_and_log(game, log, Recruit("P1-person", proclaim=True))  # pauses for payment
    submit_and_log(game, log, DecisionResponse(("P1-SH",)))

    assert game.table.seats[PlayerId.P1].honor == 2
    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(log))))
    assert restored.replay() == game


def test_a_grant_taken_in_a_production_window_round_trips_through_the_codec():
    """The grant is an answer to its own question, not a field on the payment, so what has to
    survive the codec is the extra entry on the tape rather than anything the payment carries."""
    state = dealt_table()
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        register(
            state,
            L5RCard.of(
                HoldingPrint, id="P1-refill", name="R", side=Side.DYNASTY, owner=PlayerId.P1
            ),
        )
    ]
    outlying = register(
        state,
        L5RCard.of(
            HoldingPrint,
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
        L5RCard.of(
            HoldingPrint, id="P1-buy", name="Buy", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=4
        ),
    )

    log = GameLog(initial=InitialRecord.from_state(state), first_player=PlayerId.P1)
    game = build_game(log)
    act_and_log(game, log, Pass())  # P1 declines the Action phase
    act_and_log(game, log, Pass())  # P2 declines its Open window: Action -> Battle
    act_and_log(game, log, Pass())  # Battle -> Dynasty
    act_and_log(game, log, Recruit("P1-buy"))
    submit_and_log(game, log, DecisionResponse(("P1-of",)))  # bow Outlying Farms
    submit_and_log(game, log, DecisionResponse(("P1-of",)))  # take its grant in the window

    assert outlying not in game.table.battlefield.cards  # destroyed after bowing granted
    encoded = game_log_to_dict(log)
    restored = game_log_from_dict(json.loads(json.dumps(encoded)))
    assert restored.replay() == game
    assert encoded["entries"][-2:] == [
        {"kind": "answer", "seat": "P1", "choices": ["P1-of"]},
        {"kind": "answer", "seat": "P1", "choices": ["P1-of"]},
    ]


def test_triggered_choice_replays_and_round_trips():
    # Recruiting a Wheat Farm fires its EnteredPlay trigger, which pauses to choose other Farms to
    # give a Wealth token — the recruit -> pay -> choose -> resume chain must survive replay.
    state = dealt_table()
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        register(
            state,
            L5RCard.of(
                HoldingPrint, id="P1-refill", name="R", side=Side.DYNASTY, owner=PlayerId.P1
            ),
        )
    ]
    put_in_play(
        state,
        L5RCard.of(
            HoldingPrint,
            id="P1-SH",
            name="SH",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            gold_production=8,
        ),
    )
    put_in_play(
        state,
        L5RCard.of(
            HoldingPrint,
            id="P1-other",
            name="Other Farm",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            keywords=("Farm",),
            gold_production=2,
        ),
    )
    _place_in_province(
        state,
        L5RCard.of(
            HoldingPrint,
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
    act_and_log(game, log, Pass())  # P1 declines the Action phase
    act_and_log(game, log, Pass())  # P2 declines its Open window: Action -> Battle
    act_and_log(game, log, Pass())  # Battle -> Dynasty
    act_and_log(game, log, Recruit("P1-wheat"))  # pauses for payment
    submit_and_log(game, log, DecisionResponse(("P1-SH",)))  # pays, then pauses for the choice
    submit_and_log(game, log, DecisionResponse(("P1-other",)))  # give the other Farm a token

    assert game.pending is None and game.stack == []
    assert game.table.cards_by_id["P1-other"].counters == {"wealth": 1}
    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(log))))
    assert restored.replay() == game


def test_cancelled_recruit_payment_replays_and_round_trips():
    state = dealt_table()
    put_in_play(
        state,
        L5RCard.of(
            HoldingPrint,
            id="P1-SH",
            name="SH",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            gold_production=8,
        ),
    )
    _place_in_province(
        state,
        L5RCard.of(
            HoldingPrint, id="P1-buy", name="Buy", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=5
        ),
    )

    log = GameLog(initial=InitialRecord.from_state(state), first_player=PlayerId.P1)
    game = build_game(log)
    act_and_log(game, log, Pass())  # P1 declines the Action phase
    act_and_log(game, log, Pass())  # P2 declines its Open window: Action -> Battle
    act_and_log(game, log, Pass())  # Battle -> Dynasty
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
    log = GameLog(initial=InitialRecord.from_state(dealt_table()), first_player=PlayerId.P1)
    game = build_game(log)
    while not game.awaiting_decision:  # pass out the turn, into the end-of-turn discard
        act_and_log(game, log, Pass())
    entries_before = len(log.entries)

    with pytest.raises(ValueError):  # must discard exactly one card
        submit_and_log(game, log, DecisionResponse(()))

    assert len(log.entries) == entries_before
    assert game.awaiting_decision


def test_replay_rejects_a_desynced_tape():
    log = GameLog(
        initial=InitialRecord.from_state(dealt_table()),
        first_player=PlayerId.P1,
        entries=[Act(PlayerId.P2, Pass())],  # P1 starts, so an opening P2 act is impossible
    )
    with pytest.raises(ValueError, match="out of step"):
        replay(log)


def test_decode_action_rejects_an_unknown_kind():
    # A malformed log must fail loudly, not silently mis-decode as some default action.
    with pytest.raises(ValueError):
        _decode_action({"kind": "bogus"})


ROUND_TRIPPED_ACTIONS = [
    Pass(),
    Recruit("card"),
    Recruit("card", invest=True),
    Recruit("card", proclaim=True),
    Equip("card"),
    Equip("card", invest=True),
    DynastyDiscard("card"),
    Legacy(),
    Inheritance(),
    Cycle(),
    KharmicDraw("card"),
    KharmicRefill("card"),
    ActivateAbility("card"),
]


def test_every_action_kind_is_round_tripped():
    # The list above is hand-written, so an action added to the union without a case here would
    # ship a codec nothing exercises — and only fail when someone saved a game.
    covered = {type(action) for action in ROUND_TRIPPED_ACTIONS}
    assert set(typing.get_args(Action)) - covered == set()


@pytest.mark.parametrize("action", ROUND_TRIPPED_ACTIONS)
def test_every_action_survives_a_json_round_trip(action):
    # The log is the save format and the replay tape, so an action the codec cannot carry is an
    # action that cannot be saved or replayed.
    log = GameLog(initial=InitialRecord.from_state(dealt_table()), first_player=PlayerId.P1)
    log.entries.append(Act(PlayerId.P1, action))

    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(log))))

    assert restored.entries[0].action == action

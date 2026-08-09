import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState
from yasuki_core.engine.rules import legality
from yasuki_core.engine.rules.actions import Pass
from yasuki_core.engine.session import EngineSession
from tests.yasuki_core.engine.builders import holding, province_card, put_in_play


def _board():
    """P1 with two producers and two face-up Province Holdings — enough that the Dynasty phase
    offers several Recruits and a Discard for each, so narrowing to one card is observable."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("sh", printed_id="plain_stronghold", gold_production=5))
    put_in_play(
        state, holding("millet", printed_id="millet_farm", keywords=("Farm",), gold_production=1)
    )
    put_in_play(
        state, holding("farm", printed_id="plain_farm", keywords=("Farm",), gold_production=2)
    )
    province_card(state, "cheap", printed_id="plain_holding", gold_cost=1, index=0)
    province_card(state, "dear", printed_id="other_holding", gold_cost=3, index=1)
    return EngineSession.start(state, PlayerId.P1)


def _dynasty(session):
    session.act(PlayerId.P1, Pass())
    session.act(PlayerId.P1, Pass())
    return session


def test_gold_reach_holds_a_target_independent_producer_in_its_fixed_part():
    session = _board()
    game = session.game

    fixed, variable = legality.gold_reach(game, PlayerId.P1)

    assert variable == ()
    assert fixed == 5 + 1 + 2


def test_gold_reach_counts_a_bow_time_boost_the_seat_could_opt_into():
    # Outlying Farms yields 2 more if the seat destroys it as it bows. That is optional, so it does
    # not change what the producer makes — but it does change what the seat can reach, which is what
    # decides whether a Recruit is offered at all.
    state = TableState.empty_two_seat()
    put_in_play(state, holding("outlying", printed_id="outlying_farms", gold_production=3))
    game = EngineSession.start(state, PlayerId.P1).game

    fixed, variable = legality.gold_reach(game, PlayerId.P1)

    assert variable == ()
    assert fixed == 3 + 2


def test_gold_reach_leaves_a_producer_that_reads_its_target_variable():
    # Jade Works yields +2 when paying for a Jade card, so its yield cannot be settled until the
    # purchase is known — the whole reason for the split.
    state = TableState.empty_two_seat()
    put_in_play(state, holding("jade", printed_id="jade_works", gold_production=2))
    put_in_play(state, holding("farm", printed_id="plain_farm", gold_production=3))
    province_card(state, "jadecard", printed_id="plain_holding", keywords=("Jade",), gold_cost=1)
    province_card(state, "plain", printed_id="other_holding", gold_cost=1, index=1)
    game = EngineSession.start(state, PlayerId.P1).game

    fixed, variable = legality.gold_reach(game, PlayerId.P1)

    assert fixed == 3
    assert [card.id for card in variable] == ["jade"]
    assert legality.reachable_gold(game, PlayerId.P1, game.table.cards_by_id["jadecard"]) == 3 + 4
    assert legality.reachable_gold(game, PlayerId.P1, game.table.cards_by_id["plain"]) == 3 + 2


@pytest.mark.parametrize("card_id", ["cheap", "dear"])
def test_reachable_gold_is_unchanged_by_the_fixed_variable_split(card_id):
    # reachable_gold is public and used outside legality; the split must be invisible through it.
    game = _dynasty(_board()).game
    card = game.table.cards_by_id[card_id]

    fixed, variable = legality.gold_reach(game, PlayerId.P1)
    rebuilt = fixed + sum(
        legality.effective_gold_production(game, producer, targets=(card,)) for producer in variable
    )

    assert legality.reachable_gold(game, PlayerId.P1, card) == rebuilt == 8

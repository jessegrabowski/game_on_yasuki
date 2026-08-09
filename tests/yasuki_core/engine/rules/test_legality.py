import numpy as np
import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState
from yasuki_core.engine.rules import legality
from yasuki_core.engine.rules.actions import (
    ActivateAbility,
    Cycle,
    DynastyDiscard,
    Legacy,
    Pass,
    Recruit,
)
from yasuki_core.engine.rules.agents import make_agent
from yasuki_core.engine.rules.policies import make_policy
from yasuki_core.engine.runner import Controls, run_game
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_setup import build_state_from_deck
from tests.yasuki_core.db_guard import requires_db
from tests.yasuki_core.engine.builders import holding, province_card, put_in_play

DECK = "src/yasuki_gui/assets/decks/spider_oni_control.yaml"


def _board():
    """P1 with three gold producers and two face-up Province Holdings — enough that the Dynasty
    phase offers several Recruits and a Discard for each, so narrowing to one card is observable."""
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


# Well-formed actions naming a card no board holds — never legal anywhere.
UNKNOWN_CARD = (
    Recruit("nonexistent"),
    DynastyDiscard("nonexistent"),
    ActivateAbility("nonexistent"),
)

# Plus one that names a real card in a mode it does not offer. Tied to _board's ids, so it only
# means anything against that fixture.
NEVER_LEGAL = (*UNKNOWN_CARD, Recruit("cheap", proclaim=True))  # a Holding cannot be Proclaimed


@pytest.mark.parametrize(
    "open_phase", [_board, lambda: _dynasty(_board())], ids=["action", "dynasty"]
)
def test_is_legal_accepts_exactly_what_the_enumeration_offers(open_phase):
    # is_legal and legal_actions answer the same question by different routes, so the failure worth
    # guarding is drift between them.
    session = open_phase()
    offered = legality.legal_actions(session.game, PlayerId.P1)

    assert offered, "fixture should offer something in this phase"
    for action in offered:
        assert legality.is_legal(session.game, PlayerId.P1, action), action
    for action in NEVER_LEGAL:
        assert not legality.is_legal(session.game, PlayerId.P1, action), action


def test_an_action_with_no_legality_rule_raises():
    # Action is a closed union and every member is handled, so this is only reachable by adding one
    # without a rule here — which would otherwise read as a rules bug rather than a missing case.
    game = _board().game

    with pytest.raises(ValueError, match="no legality rule"):
        legality.is_legal(game, PlayerId.P1, object())


def test_is_legal_rejects_an_action_belonging_to_another_phase():
    action_phase = _board()
    dynasty = _dynasty(_board())

    assert not legality.is_legal(action_phase.game, PlayerId.P1, Recruit("cheap"))
    assert not legality.is_legal(action_phase.game, PlayerId.P1, DynastyDiscard("cheap"))
    assert legality.is_legal(dynasty.game, PlayerId.P1, Recruit("cheap"))
    assert not legality.is_legal(dynasty.game, PlayerId.P1, Cycle())


def test_is_legal_rejects_every_action_from_the_seat_that_is_not_active():
    session = _dynasty(_board())

    assert not legality.is_legal(session.game, PlayerId.P2, Pass())
    assert not legality.is_legal(session.game, PlayerId.P2, Recruit("cheap"))


def test_is_legal_rejects_every_action_while_a_decision_is_pending():
    session = _board()
    session.act(PlayerId.P1, ActivateAbility("millet"))

    assert session.game.awaiting_decision
    assert not legality.is_legal(session.game, PlayerId.P1, Pass())


@requires_db
def test_is_legal_and_the_enumeration_agree_across_a_driven_game():
    # The fixtures above are hand-built and shallow. This walks real boards — refills, bowed
    # producers, spent gold, a used Legacy — and checks the two never diverge on any of them.
    table, first = build_state_from_deck(DECK, rng=np.random.default_rng(11))
    session = EngineSession.start(table, first, seed=11)
    controls = {seat: Controls(make_policy("economic"), make_agent("paying")) for seat in PlayerId}

    checked = 0
    for _ in run_game(session, controls, turn_limit=8):
        for seat in PlayerId:
            offered = legality.legal_actions(session.game, seat)
            for action in offered:
                assert legality.is_legal(session.game, seat, action), (seat, action)
            for action in (*UNKNOWN_CARD, Legacy(), Cycle()):
                if action not in offered:
                    assert not legality.is_legal(session.game, seat, action), (seat, action)
            checked += len(offered)

    assert checked > 100, f"only {checked} actions checked — the walk is not exercising much"


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
def test_reachable_gold_ignores_the_target_when_no_producer_reads_it(card_id):
    # reachable_gold is public and used outside legality, so the split has to stay invisible through
    # it. With nothing in the variable half, every candidate must reach the same total.
    game = _dynasty(_board()).game
    card = game.table.cards_by_id[card_id]

    assert legality.reachable_gold(game, PlayerId.P1, card) == 5 + 1 + 2

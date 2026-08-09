from typing import get_args

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState
from yasuki_core.engine.rules import legality
from yasuki_core.engine.rules.actions import (
    ACTION_TIMINGS,
    Action,
    ActionTiming,
    ActivateAbility,
    Cycle,
    DynastyDiscard,
    Legacy,
    Pass,
    Recruit,
)
from yasuki_core.engine.session import EngineSession
from tests.yasuki_core.engine.builders import (
    holding,
    province_card,
    put_in_play,
    two_seat_game,
)


def _phases_fixture():
    """P1 holding one Open ability and one Dynasty ability, each with a legal target — Millet Farm
    wants another Farm in play, the Shrine an untokened Sincerity card in a Province. Without those
    an ability is withheld for a reason that has nothing to do with timing."""
    state = TableState.empty_two_seat()
    put_in_play(
        state, holding("millet", printed_id="millet_farm", keywords=("Farm",), gold_production=1)
    )
    put_in_play(state, holding("shrine", printed_id="shrine_of_sincerity", gold_production=1))
    put_in_play(
        state, holding("farm", printed_id="plain_farm", keywords=("Farm",), gold_production=2)
    )
    province_card(state, "sincere", printed_id="plain_sincerity", keywords=("Sincerity",))
    return EngineSession.start(state, PlayerId.P1)


def test_each_rulebook_action_reports_the_designator_the_cr_prints():
    # Asserted against the action rather than through the phase it is offered in: the phase check
    # was already true before designators existed, so only this can catch a misclassification.
    game = two_seat_game()

    assert legality.timing_of(game, Cycle()) is ActionTiming.LIMITED
    assert legality.timing_of(game, Recruit("x")) is ActionTiming.DYNASTY
    assert legality.timing_of(game, DynastyDiscard("x")) is ActionTiming.DYNASTY
    assert legality.timing_of(game, Legacy()) is ActionTiming.DYNASTY


def test_every_action_has_a_designator_or_a_stated_reason_not_to():
    # ACTION_TIMINGS is the single source, so an Action added to the union without an entry would
    # only surface when someone constructed one. Pass is exempt because it is the alternative to
    # acting rather than an action; ActivateAbility because it reads its designator off the card.
    timed_elsewhere = {Pass, ActivateAbility}

    assert set(get_args(Action)) - timed_elsewhere == set(ACTION_TIMINGS)


def test_an_action_with_no_designator_is_an_error():
    with pytest.raises(ValueError, match="no designator"):
        legality.timing_of(two_seat_game(), object())


def test_a_pass_carries_no_designator():
    # A pass is the alternative to taking an action, not an action, so every Action Round accepts it
    # and no designator would be right.
    assert legality.timing_of(two_seat_game(), Pass()) is None


def test_activating_an_ability_reports_the_cards_designator():
    # Millet Farm prints "Open, bow:" and Shrine of Sincerity prints "Dynasty, bow:" — the same
    # action class, timed by the card rather than by its own type.
    game = two_seat_game()
    put_in_play(
        game, holding("millet", printed_id="millet_farm", keywords=("Farm",), gold_production=1)
    )
    put_in_play(game, holding("shrine", printed_id="shrine_of_sincerity", gold_production=1))

    assert legality.timing_of(game, ActivateAbility("millet")) is ActionTiming.OPEN
    assert legality.timing_of(game, ActivateAbility("shrine")) is ActionTiming.DYNASTY


def test_timing_a_card_with_no_activated_ability_is_an_error():
    game = two_seat_game()
    put_in_play(game, holding("plain", printed_id="plain_farm", gold_production=2))

    with pytest.raises(ValueError, match="no activated ability"):
        legality.timing_of(game, ActivateAbility("plain"))


def test_each_phase_permits_only_the_designators_its_round_allows():
    session = _phases_fixture()

    assert legality.permits(session.game, PlayerId.P1, ActionTiming.OPEN)
    assert legality.permits(session.game, PlayerId.P1, ActionTiming.LIMITED)
    assert not legality.permits(session.game, PlayerId.P1, ActionTiming.DYNASTY)

    session.act(PlayerId.P1, Pass())  # Action -> Battle: battles own their own rounds
    assert not any(legality.permits(session.game, PlayerId.P1, t) for t in ActionTiming)

    session.act(PlayerId.P1, Pass())  # Battle -> Dynasty
    assert legality.permits(session.game, PlayerId.P1, ActionTiming.DYNASTY)
    assert not legality.permits(session.game, PlayerId.P1, ActionTiming.OPEN)
    assert not legality.permits(session.game, PlayerId.P1, ActionTiming.LIMITED)


def test_a_phase_offers_only_the_abilities_its_round_permits():
    # Both cards are in play throughout, so what moves is the phase and nothing else.
    session = _phases_fixture()

    in_action = session.legal_actions(PlayerId.P1)
    session.act(PlayerId.P1, Pass())
    in_battle = session.legal_actions(PlayerId.P1)
    session.act(PlayerId.P1, Pass())
    in_dynasty = session.legal_actions(PlayerId.P1)

    assert ActivateAbility("millet") in in_action
    assert ActivateAbility("shrine") not in in_action
    assert ActivateAbility("millet") not in in_battle
    assert ActivateAbility("shrine") not in in_battle
    assert ActivateAbility("millet") not in in_dynasty
    assert ActivateAbility("shrine") in in_dynasty

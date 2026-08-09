from typing import get_args

import pytest

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
from tests.yasuki_core.engine.builders import holding, put_in_play, two_seat_game


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

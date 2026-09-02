from typing import get_args

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState
from yasuki_core.engine.rules import abilities, legality
from yasuki_core.engine.rules.actions import (
    ACTION_TIMINGS,
    Action,
    ActionTiming,
    ActivateAbility,
    Cycle,
    DynastyDiscard,
    Legacy,
    Pass,
    PlayStrategy,
    Recruit,
)
from yasuki_core.engine.rules.abilities import Ability, itself, register_ability
from yasuki_core.engine.session import EngineSession
from tests.yasuki_core.engine.builders import (
    end_phase,
    holding,
    province_card,
    put_in_play,
    two_seat_game,
)


register_ability(
    "dual",
    Ability(
        timings=(ActionTiming.BATTLE, ActionTiming.OPEN),
        label="test",
        cost=lambda game, source: [],
        targets=itself,
        effects=lambda game, source, target: [],
    ),
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

    assert legality.timings_of(game, Cycle()) == {ActionTiming.LIMITED}
    assert legality.timings_of(game, Recruit("x")) == {ActionTiming.DYNASTY}
    assert legality.timings_of(game, DynastyDiscard("x")) == {ActionTiming.DYNASTY}
    assert legality.timings_of(game, Legacy()) == {ActionTiming.DYNASTY}


def test_every_action_has_a_designator_or_a_stated_reason_not_to():
    # ACTION_TIMINGS is the single source, so an Action added to the union without an entry would
    # only surface when someone constructed one. Pass is exempt because it is the alternative to
    # acting rather than an action; ActivateAbility and PlayStrategy because they read their
    # designator off the card, which is why a Strategy can be a Battle action and an Open one.
    timed_elsewhere = {Pass, ActivateAbility, PlayStrategy}

    assert set(get_args(Action)) - timed_elsewhere == set(ACTION_TIMINGS)


def test_an_action_with_no_designator_is_an_error():
    with pytest.raises(ValueError, match="no designator"):
        legality.timings_of(two_seat_game(), object())


def test_a_pass_carries_no_designator():
    # A pass is the alternative to taking an action, not an action, so every Action Round accepts it
    # and no designator would be right.
    assert legality.timings_of(two_seat_game(), Pass()) == frozenset()


def test_activating_an_ability_reports_the_cards_designator():
    # Millet Farm prints "Open, bow:" and Shrine of Sincerity prints "Dynasty, bow:" — the same
    # action class, timed by the card rather than by its own type.
    game = two_seat_game()
    put_in_play(
        game, holding("millet", printed_id="millet_farm", keywords=("Farm",), gold_production=1)
    )
    put_in_play(game, holding("shrine", printed_id="shrine_of_sincerity", gold_production=1))

    assert legality.timings_of(game, ActivateAbility("millet")) == {ActionTiming.OPEN}
    assert legality.timings_of(game, ActivateAbility("shrine")) == {ActionTiming.DYNASTY}


def test_timing_a_card_with_no_activated_ability_is_an_error():
    game = two_seat_game()
    put_in_play(game, holding("plain", printed_id="plain_farm", gold_production=2))

    with pytest.raises(ValueError, match="no activated ability"):
        legality.timings_of(game, ActivateAbility("plain"))


def test_each_phase_permits_only_the_designators_its_round_allows():
    session = _phases_fixture()

    assert legality.permits(session.game, PlayerId.P1, ActionTiming.OPEN)
    assert legality.permits(session.game, PlayerId.P1, ActionTiming.LIMITED)
    assert not legality.permits(session.game, PlayerId.P1, ActionTiming.DYNASTY)

    end_phase(session)  # Action -> Battle: the declaration only, since battles own their own rounds
    assert legality.permits(session.game, PlayerId.P1, ActionTiming.ATTACK)
    assert not any(
        legality.permits(session.game, PlayerId.P1, t)
        for t in ActionTiming
        if t is not ActionTiming.ATTACK
    )

    end_phase(session)  # Battle -> Dynasty
    assert legality.permits(session.game, PlayerId.P1, ActionTiming.DYNASTY)
    assert not legality.permits(session.game, PlayerId.P1, ActionTiming.OPEN)
    assert not legality.permits(session.game, PlayerId.P1, ActionTiming.LIMITED)


def test_a_phase_offers_only_the_abilities_its_round_permits():
    # Both cards are in play throughout, so what moves is the phase and nothing else.
    session = _phases_fixture()

    in_action = session.legal_actions(PlayerId.P1)
    end_phase(session)
    in_battle = session.legal_actions(PlayerId.P1)
    end_phase(session)
    in_dynasty = session.legal_actions(PlayerId.P1)

    assert ActivateAbility("millet") in in_action
    assert ActivateAbility("shrine") not in in_action
    assert ActivateAbility("millet") not in in_battle
    assert ActivateAbility("shrine") not in in_battle
    assert ActivateAbility("millet") not in in_dynasty
    assert ActivateAbility("shrine") in in_dynasty


def test_a_card_printing_two_designators_is_offered_under_either():
    """ "Battle/Open" is 86 of the arc's cards: the ability is one ability, offered in any round that
    permits any designator it prints."""
    game = two_seat_game()
    card = put_in_play(game, holding("h", owner=PlayerId.P1, printed_id="dual"))

    dual = abilities.ability_for(card)
    assert abilities.activatable(game, PlayerId.P1, frozenset({ActionTiming.OPEN})) == [
        (card, dual)
    ]
    assert abilities.activatable(game, PlayerId.P1, frozenset({ActionTiming.BATTLE})) == [
        (card, dual)
    ]
    assert abilities.activatable(game, PlayerId.P1, frozenset({ActionTiming.DYNASTY})) == []
    assert legality.timings_of(game, ActivateAbility("h")) == {
        ActionTiming.BATTLE,
        ActionTiming.OPEN,
    }

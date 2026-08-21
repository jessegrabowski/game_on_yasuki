from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.actions import ActivateAbility, Pass
from yasuki_core.engine.rules.events import CardDiscarded
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.constants import Side

from tests.yasuki_core.engine.builders import holding, put_in_play, two_seat_game

P1 = PlayerId.P1


# --- Caravansary ---


def _caravansary_game(*, wealth=0):
    game = two_seat_game()
    caravansary = put_in_play(
        game,
        holding("caravansary", printed_id="caravansary", name="Caravansary", gold_production=2),
    )
    if wealth:
        caravansary.adjust_counter("wealth", wealth)
    return EngineSession.start(game.table, P1)


def _after_an_action_that_discarded(session, event) -> bool:
    """Stand the game where a Response Step opens: an action has just resolved, and ``event`` is
    what it did. No implemented action discards a Fate card yet, so the record is placed directly.

    Returns whether a Step opened, which is what separates "nobody could respond" from "the Step
    opened and this card was not offered".
    """
    session.game.action_events[:] = [event]
    return flow.open_response_window(session.game)


def test_the_caravansary_is_offered_after_your_action_discards_a_fate_card():
    session = _caravansary_game()

    assert _after_an_action_that_discarded(session, CardDiscarded("some-fate", Side.FATE, P1))

    assert ActivateAbility("caravansary") in session.legal_actions(P1)


def test_taking_the_response_banks_a_wealth_token():
    session = _caravansary_game()
    _after_an_action_that_discarded(session, CardDiscarded("some-fate", Side.FATE, P1))

    session.act(P1, ActivateAbility("caravansary"))

    assert session.game.table.cards_by_id["caravansary"].counters == {"wealth": 1}


def test_passing_the_response_leaves_the_token_unclaimed():
    """A Response is an action: declining the Step is declining the token."""
    session = _caravansary_game()
    _after_an_action_that_discarded(session, CardDiscarded("some-fate", Side.FATE, P1))

    session.act(P1, Pass())

    assert session.game.table.cards_by_id["caravansary"].counters == {}


def test_the_response_answers_one_discard_once():
    """Nothing else rations it — it costs no bow — so the Step itself does."""
    session = _caravansary_game()
    _after_an_action_that_discarded(session, CardDiscarded("some-fate", Side.FATE, P1))

    session.act(P1, ActivateAbility("caravansary"))

    assert ActivateAbility("caravansary") not in session.legal_actions(P1)


def test_a_later_step_offers_the_response_again():
    """The once-a-Step limit is scoped to the Step: a fresh action that discards again offers the
    card again, rather than spending it for the rest of the turn."""
    session = _caravansary_game()
    _after_an_action_that_discarded(session, CardDiscarded("some-fate", Side.FATE, P1))
    session.act(P1, ActivateAbility("caravansary"))
    session.act(PlayerId.P2, Pass())
    session.act(P1, Pass())  # both pass, so the Step closes

    assert _after_an_action_that_discarded(session, CardDiscarded("later-fate", Side.FATE, P1))
    assert ActivateAbility("caravansary") in session.legal_actions(P1)


def test_an_opponents_discard_offers_you_nothing():
    session = _caravansary_game()

    opened = _after_an_action_that_discarded(
        session, CardDiscarded("some-fate", Side.FATE, PlayerId.P2)
    )

    assert not opened  # nobody held a Response, so no Step was opened at all
    assert ActivateAbility("caravansary") not in session.legal_actions(P1)


def test_a_discard_no_player_made_offers_nothing():
    """Trimming to the maximum hand size is a step of the turn rather than an action (CR, Drawing
    and Discarding Fate Cards), so "if the action was yours" has no action to claim."""
    session = _caravansary_game()

    opened = _after_an_action_that_discarded(
        session, CardDiscarded("some-fate", Side.FATE, Rulebook.MAXIMUM_HAND_SIZE)
    )

    assert not opened
    assert ActivateAbility("caravansary") not in session.legal_actions(P1)


def test_a_dynasty_discard_offers_nothing():
    session = _caravansary_game()

    opened = _after_an_action_that_discarded(
        session, CardDiscarded("some-dynasty", Side.DYNASTY, P1)
    )

    assert not opened
    assert ActivateAbility("caravansary") not in session.legal_actions(P1)


def test_a_caravansary_already_at_three_is_not_offered():
    session = _caravansary_game(wealth=3)

    opened = _after_an_action_that_discarded(session, CardDiscarded("some-fate", Side.FATE, P1))

    assert not opened
    assert ActivateAbility("caravansary") not in session.legal_actions(P1)

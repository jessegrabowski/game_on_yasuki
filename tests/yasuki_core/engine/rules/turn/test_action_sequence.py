import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.abilities.registry import _ABILITIES, register_ability
from yasuki_core.engine.rules.board.queries import personalities_in_play, rulebook_proxy
from yasuki_core.engine.rules.rulebook import proxies
from yasuki_core.engine.rules.rulebook.lobby import LOBBY
from yasuki_core.engine.rules.turn import action_sequence, sequence
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, ActivateAbility
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces.constants import ONYX_LOBBY_PROXY_ID

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    holding,
    personality,
    put_in_play,
    two_seat_game,
)

P1 = PlayerId.P1


def test_an_unhandled_action_is_refused_rather_than_ignored():
    # perform is the entry point for a player's chosen action. Falling through would accept the
    # action and silently do nothing, which is indistinguishable from a legal no-op.
    class Unregistered:
        pass

    with pytest.raises(ValueError, match="no handler for action"):
        action_sequence.perform(two_seat_game(), Unregistered())


def test_the_announcing_seat_is_recorded_until_the_action_is_forgotten():
    game = two_seat_game()
    game.table.seats[P1].honor = 10
    put_in_play(game, personality("courtier", personal_honor=2))
    proxies.spawn_rulebook_proxies(game)
    lobby = ActivateAbility(rulebook_proxy(game, P1, ONYX_LOBBY_PROXY_ID).id, LOBBY)

    action_sequence.perform(game, lobby)

    assert game.action_seat is P1
    sequence.forget_action(game)
    assert game.action_seat is None
    assert game.action_targets == ()


def test_a_chosen_target_is_recorded_on_the_action():
    state = TableState.empty_two_seat()
    put_in_play(state, personality("bearer"))
    put_in_play(state, personality("bystander"))
    attached(state, attachment("tanto", printed_id="dull_tanto"), "bearer")
    session = EngineSession.start(state, P1)

    session.act(P1, ActivateAbility("tanto"))
    session.submit(P1, DecisionResponse(("bystander",)))

    assert session.game.action_targets == ("bystander",)


def test_every_card_an_untargeted_ability_hits_is_recorded_on_the_action():
    state = TableState.empty_two_seat()
    put_in_play(state, holding("traders", printed_id="moto_traders"))
    session = EngineSession.start(state, P1)

    session.act(P1, ActivateAbility("traders"))

    assert session.game.action_targets == ("traders",)


RESPONSE_PROBE = "probe_response_targets_a_personality"


def _response_probe_registered() -> None:
    register_ability(
        RESPONSE_PROBE,
        Ability(
            timings=(ActionTiming.RESPONSE,),
            label="Response: point at a Personality",
            cost=no_cost,
            targets=lambda game, source: [
                card.id for card in personalities_in_play(game) if card.id != source.id
            ],
            effects=lambda game, source, target: [],
        ),
    )


def test_a_responses_own_target_is_not_recorded_on_the_action_it_answers():
    # Every responder in a Step reads the same record, so one responder's target must not be
    # read by the next as something the answered action did.
    _response_probe_registered()
    try:
        state = TableState.empty_two_seat()
        put_in_play(state, holding("traders", printed_id="moto_traders"))
        put_in_play(state, personality("responder", printed_id=RESPONSE_PROBE))
        put_in_play(state, personality("bystander"))
        session = EngineSession.start(state, P1)
        session.act(P1, ActivateAbility("traders"))

        session.act(P1, ActivateAbility("responder"))
        session.submit(P1, DecisionResponse(("bystander",)))

        assert isinstance(session.game.action, ActivateAbility)
        assert session.game.action_targets == ("traders",)
    finally:
        _ABILITIES.pop(RESPONSE_PROBE)

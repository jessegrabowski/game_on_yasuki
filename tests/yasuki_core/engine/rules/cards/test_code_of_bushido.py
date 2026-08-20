from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.cards.code_of_bushido import MEDIUM_FOLLOWER
from yasuki_core.engine.rules.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.rules.effects import AttachCard
from yasuki_core.engine.rules.flow import submit
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.table import ZoneKey, ZoneRole

from tests.yasuki_core.engine.builders import (
    attachment,
    personality,
    put_in_play,
    register,
    token_template,
    two_seat_game,
)

P1 = PlayerId.P1


# --- Ichiro Yojimbo ---


def _yojimbo_game():
    """Ichiro Yojimbo waiting in hand, with two Personalities his second Follower could join."""
    game = two_seat_game()
    token_template(game, MEDIUM_FOLLOWER, name="Medium Follower", card_type="Follower", force=1)
    put_in_play(game, personality("lord", force=2, chi=3))
    put_in_play(game, personality("cousin", force=2, chi=3))
    hand = game.table.zones[ZoneKey(P1, ZoneRole.HAND)]
    hand.add(register(game.table, attachment("ichiro", printed_id="ichiro_yojimbo", force=2)))
    return game


def test_ichiro_yojimbo_brings_a_second_follower():
    game = _yojimbo_game()

    resolve_effects(game, [AttachCard("ichiro", "lord")])
    assert isinstance(game.pending, ChooseCards)
    submit(game, DecisionResponse(("cousin",)))

    created = attachments_of(game, game.table.cards_by_id["cousin"])[0]
    assert created.name == "Medium Follower"
    assert created.is_token is True


def test_the_second_follower_need_not_join_the_personality_ichiro_did():
    """He arrives on one Personality and the Follower he brings may go to another, so both are
    offered."""
    game = _yojimbo_game()

    resolve_effects(game, [AttachCard("ichiro", "lord")])

    assert set(game.pending.candidates) == {"lord", "cousin"}


def test_only_ichiros_own_arrival_brings_a_follower():
    """The trigger fires for every copy in play, so it has to know which one arrived."""
    game = _yojimbo_game()
    put_in_play(game, personality("other", force=2, chi=3))
    resolve_effects(game, [AttachCard("ichiro", "lord")])
    submit(game, DecisionResponse(("lord",)))
    plain = register(game.table, attachment("plain", force=1))
    game.table.zones[ZoneKey(P1, ZoneRole.HAND)].add(plain)

    resolve_effects(game, [AttachCard("plain", "other")])

    assert game.pending is None
    assert attachments_of(game, game.table.cards_by_id["other"]) == (plain,)

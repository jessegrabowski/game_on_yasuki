from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.cards.torn_asunder import KAXT
from yasuki_core.engine.rules.economy import effective_chi, effective_force
from yasuki_core.engine.rules.effects import Destroy
from yasuki_core.engine.rules.legality import card_alignments
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core import ruleset

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    personality,
    put_in_play,
    stronghold,
    token_template,
    two_seat_game,
)

P1 = PlayerId.P1


# --- Goju Kaxt ---


def _kaxt_game(*, clan: str | None = "Scorpion"):
    """Kaxt attached to a Personality, under a Stronghold of ``clan``."""
    game = two_seat_game()
    token_template(
        game,
        KAXT,
        name="Kaxt",
        card_type="Personality",
        keywords=("Ninja", "Unaligned"),
        force=4,
        chi=3,
    )
    put_in_play(game, stronghold(P1, gold_production=5, clan=clan))
    put_in_play(game, personality("host", force=2, chi=3))
    attached(game, attachment("kaxt", printed_id="goju_kaxt", force=2), "host")
    return game


def _returned(game):
    return next(card for card in game.table.battlefield.cards if card.is_token)


def test_goju_kaxt_comes_back_as_a_personality_when_he_is_destroyed():
    game = _kaxt_game()

    resolve_effects(game, [Destroy("kaxt", P1)])

    kaxt = _returned(game)
    assert kaxt.name == "Kaxt"
    assert effective_force(game, kaxt) == 4 and effective_chi(game, kaxt) == 3


def test_the_ninja_who_returns_belongs_to_the_clan_his_controller_plays():
    """ "With your Clan Alignment" — the token prints Ninja, which is no alignment at all."""
    game = _kaxt_game(clan="Scorpion")

    resolve_effects(game, [Destroy("kaxt", P1)])

    kaxt = _returned(game)
    assert kaxt.clan == "Scorpion"
    assert card_alignments(kaxt) == {ruleset.SCORPION}


def test_an_unaligned_controller_gets_the_ninja_as_printed():
    game = _kaxt_game(clan="Ninja")

    resolve_effects(game, [Destroy("kaxt", P1)])

    assert card_alignments(_returned(game)) == set()


def test_kaxt_returns_when_his_personality_takes_him_down_with_him():
    """A unit leaves play together, so the Follower's own destruction is announced either way."""
    game = _kaxt_game()

    resolve_effects(game, [Destroy("host", P1)])

    assert _returned(game).name == "Kaxt"


def test_another_follower_falling_does_not_bring_kaxt_back():
    game = _kaxt_game()
    attached(game, attachment("spear", force=1), "host")

    resolve_effects(game, [Destroy("spear", P1)])

    assert not [card for card in game.table.battlefield.cards if card.is_token]

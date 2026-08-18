import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.rules.units import followers_of, unit_force
from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    personality,
    put_in_play,
    two_seat_game,
)

P1 = PlayerId.P1


def _unit(*, hero_bowed: bool, follower_bowed: bool, item_bowed: bool):
    """A Personality of Force 3, one Follower of Force 5, and one Item granting +2, each bowed or
    not. The Item's 2 reaches the total through the Personality; the Follower's 5 stands on its
    own."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", force=3))
    follower = attached(
        game, attachment("foll", attachment_type=AttachmentType.FOLLOWER, force=5), "hero"
    )
    item = attached(game, attachment("item", force_modifier=2), "hero")
    for card, bowed in ((hero, hero_bowed), (follower, follower_bowed), (item, item_bowed)):
        if bowed:
            card.bow()
    return game, hero


# Straight from the CR: outside battle resolution every card counts, bowed or not; inside it a bowed
# Personality and a bowed Follower drop out, while a bowed Item still lends the Personality its
# Force. A reviewer should be able to check this table against the rule without reading the code.
#
#   hero    follower  item     outside  in battle
_CASES = [
    (False, False, False, 10, 10),
    (False, False, True, 10, 10),  # a bowed Item still gives its modifier to the Personality
    (False, True, False, 10, 5),  # the bowed Follower drops; hero 3 + item 2 remain
    (False, True, True, 10, 5),
    (True, False, False, 10, 5),  # the bowed hero drops, taking the Item's 2 with him
    (True, False, True, 10, 5),
    (True, True, False, 10, 0),
    (True, True, True, 10, 0),
]


@pytest.mark.parametrize("hero_bowed,follower_bowed,item_bowed,outside,in_battle", _CASES)
def test_unit_force_across_every_bowed_combination(
    hero_bowed, follower_bowed, item_bowed, outside, in_battle
):
    game, hero = _unit(hero_bowed=hero_bowed, follower_bowed=follower_bowed, item_bowed=item_bowed)

    assert unit_force(game, hero) == outside
    assert unit_force(game, hero, in_battle_resolution=True) == in_battle


def test_a_bowed_item_still_reaches_an_unbowed_personality_in_battle():
    """Named separately because it is the asymmetry the rule exists to state: a Follower's bowing
    silences it, an Item's does not."""
    game, hero = _unit(hero_bowed=False, follower_bowed=False, item_bowed=True)

    assert unit_force(game, hero, in_battle_resolution=True) == 10


def test_a_bowed_personality_takes_his_items_force_with_him():
    """The other half of the same rule: the Item's Force rides on the Personality, so it goes when
    he does even though the Item itself is unbowed."""
    game, hero = _unit(hero_bowed=True, follower_bowed=False, item_bowed=False)

    assert unit_force(game, hero, in_battle_resolution=True) == 5


def test_a_personality_alone_is_a_unit_of_one():
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", force=3))

    assert unit_force(game, hero) == 3
    assert unit_force(game, hero, in_battle_resolution=True) == 3


def test_only_followers_stand_in_the_unit():
    """An Item is in the unit but is not a Follower — it lends Force rather than carrying it, so
    counting it among the Followers would double its contribution."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))
    follower = attached(game, attachment("foll", attachment_type=AttachmentType.FOLLOWER), "hero")
    attached(game, attachment("item"), "hero")

    assert followers_of(game, hero) == (follower,)


def test_every_follower_counts_and_each_at_its_own_effective_force():
    """Two Followers rather than one, and one of them under a penalty — a total that reads a
    Follower's printed Force, or stops at the first, gets both of these wrong."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", force=3))
    attached(game, attachment("a", attachment_type=AttachmentType.FOLLOWER, force=5), "hero")
    weakened = attached(
        game, attachment("b", attachment_type=AttachmentType.FOLLOWER, force=4), "hero"
    )
    game.modifiers.append(
        Modifier("curse", weakened.id, Stat.FORCE, -3, Duration.UNTIL_END_OF_TURN)
    )

    assert unit_force(game, hero) == 9  # 3 + 5 + (4 - 3)

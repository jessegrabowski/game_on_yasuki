from yasuki_core.engine import ops
from yasuki_core.engine.rules.economy import effective_force, effective_personal_honor

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    personality,
    put_in_play,
    two_seat_game,
)


def test_haramaki_do_gives_its_personality_both_halves_of_what_it_says():
    """The +2F is printed on the card and needs no handler; the +1PH is text, and only the handler
    delivers it. A test asserting one half alone passes with the other half missing."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", force=2, personal_honor=2))
    attached(game, attachment("armor", printed_id="haramaki_do", force_modifier=2), "hero")

    assert effective_force(game, hero) == 4
    assert effective_personal_honor(game, hero) == 3


def test_the_granted_honor_leaves_when_the_armor_does():
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", force=2, personal_honor=2))
    armor = attached(game, attachment("armor", printed_id="haramaki_do", force_modifier=2), "hero")

    ops.detach(game.table, armor)

    assert effective_personal_honor(game, hero) == 2

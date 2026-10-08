from yasuki_core.engine.rules.stats.card_values import effective_chi, effective_force
from yasuki_core.engine.rules.stats.stat_grants import granted_stats
from yasuki_core.engine.rules.vocabulary.modifiers import Stat

from tests.yasuki_core.engine.builders import holding, personality, put_in_play, two_seat_game


def _one_force_to_every_bowed_personality(game, source, card, stat):
    return (1,) if stat is Stat.FORCE and card.bowed else ()


def test_a_grant_reaches_the_cards_its_handler_names_and_only_the_stat_it_names(granting):
    granting("grant_probe", _one_force_to_every_bowed_personality)
    game = two_seat_game()
    put_in_play(game, holding("shrine", printed_id="grant_probe"))
    upright = put_in_play(game, personality("upright", force=2))
    bowed = put_in_play(game, personality("bowed", force=2))
    bowed.bow()

    assert effective_force(game, upright) == 2
    assert effective_force(game, bowed) == 3
    assert effective_chi(game, bowed) == 3


def test_a_grant_ends_when_the_granting_card_leaves_play(granting):
    granting("grant_probe", _one_force_to_every_bowed_personality)
    game = two_seat_game()
    shrine = put_in_play(game, holding("shrine", printed_id="grant_probe"))
    bowed = put_in_play(game, personality("bowed", force=2))
    bowed.bow()
    assert list(granted_stats(game, bowed, Stat.FORCE)) == [(shrine, 0, 1)]

    game.table.battlefield.remove(shrine)

    assert list(granted_stats(game, bowed, Stat.FORCE)) == []


def test_each_clause_of_a_text_is_its_own_change(granting):
    granting("grant_probe", lambda game, source, card, stat: (-2, 0, 1))
    game = two_seat_game()
    shrine = put_in_play(game, holding("shrine", printed_id="grant_probe"))
    hero = put_in_play(game, personality("hero", force=4))

    assert list(granted_stats(game, hero, Stat.FORCE)) == [(shrine, 0, -2), (shrine, 2, 1)]

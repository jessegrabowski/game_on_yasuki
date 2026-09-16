from yasuki_core.engine.rules.stats.card_values import effective_chi, effective_force
from yasuki_core.engine.rules.stats.stat_grants import STAT_GRANTS, granted_stats, stat_grant
from yasuki_core.engine.rules.vocabulary.modifiers import Stat

from tests.yasuki_core.engine.builders import holding, personality, put_in_play, two_seat_game


def _one_force_to_every_bowed_personality(game, source, card, stat):
    return 1 if stat is Stat.FORCE and card.bowed else 0


def test_a_grant_reaches_the_cards_its_handler_names_and_only_the_stat_it_names():
    stat_grant("grant_probe")(_one_force_to_every_bowed_personality)

    try:
        game = two_seat_game()
        put_in_play(game, holding("shrine", printed_id="grant_probe"))
        upright = put_in_play(game, personality("upright", force=2))
        bowed = put_in_play(game, personality("bowed", force=2))
        bowed.bow()

        assert effective_force(game, upright) == 2
        assert effective_force(game, bowed) == 3
        assert effective_chi(game, bowed) == 3
    finally:
        STAT_GRANTS.pop("grant_probe", None)


def test_a_grant_ends_when_the_granting_card_leaves_play():
    stat_grant("grant_probe")(_one_force_to_every_bowed_personality)

    try:
        game = two_seat_game()
        shrine = put_in_play(game, holding("shrine", printed_id="grant_probe"))
        bowed = put_in_play(game, personality("bowed", force=2))
        bowed.bow()
        assert list(granted_stats(game, bowed, Stat.FORCE)) == [(shrine, 1)]

        game.table.battlefield.remove(shrine)

        assert list(granted_stats(game, bowed, Stat.FORCE)) == []
    finally:
        STAT_GRANTS.pop("grant_probe", None)

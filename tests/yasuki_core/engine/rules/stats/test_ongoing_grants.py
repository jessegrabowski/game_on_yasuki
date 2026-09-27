from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.modifiers import (
    DuelStatOverride,
    Duration,
    KeywordGrant,
    Modifier,
    Stat,
)
from yasuki_core.engine.rules.stats.ongoing_grants import grant_applies, named_duel_stat
from yasuki_core.engine.rules.turn.structure import DUEL_CONSEQUENCES

from tests.yasuki_core.engine.builders import holding, personality, put_in_play, two_seat_game


def test_a_while_source_in_play_record_holds_only_while_its_source_is_on_the_board():
    game = two_seat_game()
    source = put_in_play(game, holding("P1-source", owner=PlayerId.P1))
    target = put_in_play(game, holding("P1-target", owner=PlayerId.P1))
    recorded = Modifier(
        source.id, target.id, Stat.GOLD_PRODUCTION, 1, Duration.WHILE_SOURCE_IN_PLAY
    )

    assert grant_applies(game, recorded) is True

    game.table.battlefield.remove(source)

    assert grant_applies(game, recorded) is False


def test_every_other_duration_holds_without_a_source_on_the_board():
    # The predicate is the one place four record types agree on what "still in force" means, so a
    # duration that stops being checked here silently outlives its source everywhere at once.
    game = two_seat_game()
    target = put_in_play(game, holding("P1-target", owner=PlayerId.P1))

    for duration in set(Duration) - {Duration.WHILE_SOURCE_IN_PLAY}:
        recorded = KeywordGrant("never-in-play", target.id, "Cavalry", duration)
        assert grant_applies(game, recorded) is True, duration


def test_the_last_named_duel_stat_is_the_one_a_duel_compares():
    game = two_seat_game()
    duelist = put_in_play(game, personality("P1-duelist", owner=PlayerId.P1))
    game.ongoing.append(DuelStatOverride("first", duelist.id, Stat.FORCE, DUEL_CONSEQUENCES))
    game.ongoing.append(
        DuelStatOverride("second", duelist.id, Stat.PERSONAL_HONOR, DUEL_CONSEQUENCES)
    )

    assert named_duel_stat(game, duelist.id) is Stat.PERSONAL_HONOR
    assert named_duel_stat(game, "nobody") is None


def test_a_duel_stat_named_by_a_source_off_the_board_is_not_read():
    game = two_seat_game()
    duelist = put_in_play(game, personality("P1-duelist", owner=PlayerId.P1))
    game.ongoing.append(
        DuelStatOverride("never-in-play", duelist.id, Stat.FORCE, Duration.WHILE_SOURCE_IN_PLAY)
    )

    assert named_duel_stat(game, duelist.id) is None

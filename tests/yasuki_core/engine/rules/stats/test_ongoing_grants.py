from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.modifiers import Duration, KeywordGrant, Modifier, Stat
from yasuki_core.engine.rules.stats.ongoing_grants import grant_applies

from tests.yasuki_core.engine.builders import holding, put_in_play, two_seat_game


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

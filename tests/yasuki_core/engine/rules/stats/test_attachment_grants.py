from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.engine.rules.stats.attachment_grants import (
    ATTACHMENT_GRANTS,
    attachment_grant,
    granted_stat,
)

from tests.yasuki_core.engine.builders import attached, attachment, personality, put_in_play
from tests.yasuki_core.engine.builders import two_seat_game

P1 = PlayerId.P1


def test_a_card_with_no_grant_gives_nothing():
    """The registry is sparse. Almost no attachment grants anything beyond what it prints, so the
    absent case is the one this read answers most often."""
    game = two_seat_game()
    host = put_in_play(game, personality("host", owner=P1))
    item = attached(game, attachment("plain", owner=P1), "host")

    assert granted_stat(game, item, host, Stat.PERSONAL_HONOR) == 0


def test_a_grant_reaches_only_the_stat_it_names():
    """Haramaki-do prints +2F and grants +1PH in its text. Reading the granted half for Force must
    give nothing, or the printed modifier would be counted twice."""
    game = two_seat_game()
    host = put_in_play(game, personality("host", owner=P1))
    item = attached(game, attachment("grants", owner=P1, printed_id="grants_ph"), "host")
    attachment_grant("grants_ph")(lambda game_, attached_, host_: {Stat.PERSONAL_HONOR: 1})
    try:
        assert granted_stat(game, item, host, Stat.PERSONAL_HONOR) == 1
        assert granted_stat(game, item, host, Stat.FORCE) == 0
    finally:
        ATTACHMENT_GRANTS.pop("grants_ph", None)

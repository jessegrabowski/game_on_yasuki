import pytest

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.board.clans import is_clan

from tests.yasuki_core.engine.builders import put_in_play, stronghold, two_seat_game


@pytest.mark.parametrize(
    "printed, asked, expected",
    [
        ("Lion", ruleset.LION, True),
        ("Lion Clan", ruleset.LION, True),
        ("Naga", ruleset.AKASHA, True),
        ("Akasha", ruleset.NAGA, True),
        ("Lion", ruleset.CRANE, False),
        ("Fox", "fox", False),
    ],
    ids=[
        "plain",
        "spelled-in-full",
        "naga-is-akasha",
        "akasha-is-naga",
        "other-clan",
        "no-alignment",
    ],
)
def test_is_clan_compares_alignments_rather_than_strings(printed, asked, expected):
    # Two cards print their clan as "Lion Clan" where 555 print "Lion", and the arc holds Naga and
    # Akasha to be one alignment. A string comparison would read all three as different clans, and
    # a discount keyed on one would quietly never apply.
    game = two_seat_game()
    put_in_play(game, stronghold(PlayerId.P1, clan=printed))

    assert is_clan(game, PlayerId.P1, asked) is expected


def test_a_seat_with_no_stronghold_plays_no_clan():
    game = two_seat_game()

    assert is_clan(game, PlayerId.P1, ruleset.LION) is False


def test_a_stronghold_printing_several_clans_plays_them_all():
    """A Stronghold is a card, and a card may print more than one clan -- so the seat answers to each
    of them, the way a multi-clan Personality answers to each of its own."""
    game = two_seat_game()
    put_in_play(game, stronghold(PlayerId.P1, clans=("Lion", "Crane")))

    assert is_clan(game, PlayerId.P1, "Lion")
    assert is_clan(game, PlayerId.P1, "Crane")
    assert not is_clan(game, PlayerId.P1, "Scorpion")

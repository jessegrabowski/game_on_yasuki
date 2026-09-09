from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.board.queries import has_keyword
from yasuki_core.engine.rules.stats.keyword_grants import KEYWORD_GRANTS, keyword_grant
from yasuki_core.engine.rules.board.seats import (
    cards_in_play,
    cards_named,
    opposing_seats,
    seat_controls_printed,
    seat_stronghold,
    went_second,
)

from tests.yasuki_core.engine.builders import holding, put_in_play, stronghold, two_seat_game


def test_went_second_is_true_only_for_the_non_first_player():
    game = two_seat_game()  # first_player is P1
    assert went_second(game, PlayerId.P1) is False
    assert went_second(game, PlayerId.P2) is True


def test_seat_controls_matches_a_keyword_and_can_exclude_a_card():
    game = two_seat_game()
    dockside = put_in_play(game, holding("P1-dockside", owner=PlayerId.P1, keywords=("Market",)))
    put_in_play(game, holding("P1-other-market", owner=PlayerId.P1, keywords=("Market",)))
    put_in_play(game, holding("P2-market", owner=PlayerId.P2, keywords=("Market",)))

    assert seat_controls_printed(game, PlayerId.P1, "Market") is True
    assert seat_controls_printed(game, PlayerId.P1, "Port") is False
    # "another Market" -- excluding the asking card still finds the second one.
    assert seat_controls_printed(game, PlayerId.P1, "Market", other_than=dockside) is True


def test_seat_controls_other_than_the_only_match_is_false():
    game = two_seat_game()
    lone = put_in_play(game, holding("P1-lone", owner=PlayerId.P1, keywords=("Market",)))
    # An opponent's Market is not the seat's, so excluding the only one it holds finds nothing.
    put_in_play(game, holding("P2-market", owner=PlayerId.P2, keywords=("Market",)))

    assert seat_controls_printed(game, PlayerId.P1, "Market", other_than=lone) is False


def test_opposing_seats_is_every_other_seat_in_table_order():
    game = two_seat_game()

    assert opposing_seats(game, PlayerId.P1) == (PlayerId.P2,)
    assert opposing_seats(game, PlayerId.P2) == (PlayerId.P1,)


def test_cards_in_play_is_only_the_seats_own():
    game = two_seat_game()
    mine = put_in_play(game, holding("P1-h", owner=PlayerId.P1))
    put_in_play(game, holding("P2-h", owner=PlayerId.P2))

    assert cards_in_play(game, PlayerId.P1) == (mine,)


def test_cards_named_matches_the_print_and_not_the_instance():
    """A card that speaks about another copy of a named card is asking about the print, so two
    copies both answer and the seat's other Holdings do not."""
    game = two_seat_game()
    first = put_in_play(game, holding("P1-farm-a", owner=PlayerId.P1, printed_id="rice_farm"))
    second = put_in_play(game, holding("P1-farm-b", owner=PlayerId.P1, printed_id="rice_farm"))
    put_in_play(game, holding("P1-other", owner=PlayerId.P1, printed_id="modest_farm"))
    put_in_play(game, holding("P2-farm", owner=PlayerId.P2, printed_id="rice_farm"))

    assert cards_named(game, PlayerId.P1, "rice_farm") == (first, second)
    assert cards_named(game, PlayerId.P1, "no_such_card") == ()


def test_seat_stronghold_is_the_seats_own_and_none_without_one():
    game = two_seat_game()
    mine = put_in_play(game, stronghold(PlayerId.P1))
    put_in_play(game, stronghold(PlayerId.P2))

    assert seat_stronghold(game, PlayerId.P1) is mine
    assert seat_stronghold(game, None) is None


def test_seat_controls_reads_printed_keywords_and_not_granted_ones():
    # The divergence from has_keyword is deliberate: seat_controls_printed is what a
    # keyword-granting card calls to decide what it grants, so reading effective keywords here
    # would make two granting cards recurse into each other. Pins the limitation so a later cycle
    # guard is a deliberate change rather than an accident.
    game = two_seat_game()
    granted = put_in_play(game, holding("P1-docks", owner=PlayerId.P1, printed_id="seat_probe"))

    @keyword_grant("seat_probe")
    def _grants_port(card, game_, seat):
        return ("Port",)

    try:
        assert has_keyword(game, granted, "Port") is True
        assert seat_controls_printed(game, PlayerId.P1, "Port") is False
    finally:
        KEYWORD_GRANTS.pop("seat_probe", None)

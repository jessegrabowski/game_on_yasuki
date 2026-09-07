import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.board.queries import has_keyword, owned_holdings, province_key_of
from yasuki_core.engine.rules.keyword_grants import keyword_grant, KEYWORD_GRANTS

from tests.yasuki_core.engine.builders import (
    holding,
    province_card,
    put_in_play,
    stronghold,
    two_seat_game,
)


def test_owned_holdings_without_a_keyword_takes_them_all():
    """Kitsu Watanabe spends "your target Holding", any of them, so the lookup answers that too
    rather than making the card scan the battlefield for itself."""
    game = two_seat_game()
    quay = put_in_play(game, holding("P1-quay", owner=PlayerId.P1, keywords=("Port",)))
    plain = put_in_play(game, holding("P1-plain", owner=PlayerId.P1))
    put_in_play(game, holding("P2-theirs", owner=PlayerId.P2))
    put_in_play(game, stronghold(PlayerId.P1, gold_production=5))

    assert owned_holdings(game, PlayerId.P1) == [quay, plain]


def test_a_keyword_lookup_sees_a_keyword_the_card_grants_itself():
    """Keyword lookups read effective keywords, so a card whose own condition grants one is found by
    the same searches as a card that prints it. Registered here rather than leaning on a real card:
    today only Shrine of Courtesy grants anything, and it grants Legacy, which no lookup asks for."""
    game = two_seat_game()
    granted = put_in_play(game, holding("P1-docks", owner=PlayerId.P1, printed_id="keyword_probe"))
    printed = put_in_play(game, holding("P1-quay", owner=PlayerId.P1, keywords=("Port",)))

    assert owned_holdings(game, PlayerId.P1, "Port") == [printed]

    @keyword_grant("keyword_probe")
    def _grants_port(card, game, seat):
        return ("Port",)

    try:
        assert owned_holdings(game, PlayerId.P1, "Port") == [granted, printed]
    finally:
        KEYWORD_GRANTS.pop("keyword_probe", None)


def test_has_keyword_ignores_case_on_both_sides():
    """The case-insensitive match is the only thing separating this from ``keyword in
    effective_keywords``, and card text spells a keyword however the printing did."""
    game = two_seat_game()
    card = put_in_play(game, holding("P1-quay", owner=PlayerId.P1, keywords=("Port",)))

    assert has_keyword(game, card, "port") is True
    assert has_keyword(game, card, "PORT") is True
    assert has_keyword(game, card, "Harbor") is False


def test_province_key_of_raises_when_no_province_holds_the_card():
    """The raising variant exists so a caller that already knows the card is in a Province does not
    carry an impossible None; a card in play is in no Province at all."""
    game = two_seat_game()
    provincial = province_card(game, "P1-farm", seat=PlayerId.P1)
    in_play = put_in_play(game, holding("P1-built", owner=PlayerId.P1))

    assert province_key_of(game, PlayerId.P1, provincial.id).owner is PlayerId.P1

    with pytest.raises(ValueError, match=in_play.id):
        province_key_of(game, PlayerId.P1, in_play.id)

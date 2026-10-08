import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.locations import CardLocation, location_holding
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side

from tests.yasuki_core.engine.builders import fate_card, put_in_play, register, two_seat_game


@pytest.mark.parametrize(
    ("role", "location"),
    [
        (ZoneRole.HAND, CardLocation.HAND),
        (ZoneRole.FATE_DISCARD, CardLocation.DISCARD),
        (ZoneRole.FATE_BANISH, CardLocation.BANISH),
    ],
)
def test_a_card_in_a_zone_is_at_that_zones_location(role, location):
    game = two_seat_game()
    card = register(game.table, fate_card("card", PlayerId.P1))
    game.table.zones[ZoneKey(PlayerId.P1, role)].add(card)

    assert location_holding(game.table, card) is location


def test_a_card_in_play_or_a_deck_or_nowhere():
    game = two_seat_game()
    in_play = put_in_play(game, fate_card("in-play", PlayerId.P1))
    in_deck = register(game.table, fate_card("in-deck", PlayerId.P1))
    game.table.decks[DeckKey(PlayerId.P1, Side.FATE)].cards.append(in_deck)
    nowhere = register(game.table, fate_card("nowhere", PlayerId.P1))

    assert location_holding(game.table, in_play) is CardLocation.BATTLEFIELD
    assert location_holding(game.table, in_deck) is CardLocation.DECK
    assert location_holding(game.table, nowhere) is None

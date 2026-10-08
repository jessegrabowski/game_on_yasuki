from enum import Enum

from yasuki_core.engine.table import TableState, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard


class CardLocation(str, Enum):
    """Where a card must be for its behavior to be offered or its trigger to be collected, and
    where a discarded card was discarded from. Distinct from ``ZoneRole``, which cannot name the
    battlefield or a deck, since those are fields of their own on the table, not keyed zones."""

    BATTLEFIELD = "battlefield"
    PROVINCE = "province"
    HAND = "hand"
    DECK = "deck"
    # A seat's rulebook zone, where a proxy card stands for abilities the rules give every player.
    RULEBOOK = "rulebook"
    # Either of a seat's discard piles, which no printed ability acts from, but which an ability a
    # card grants may ("from your target Ring in play or your discard pile").
    DISCARD = "discard"
    # A seat's focusing area, which a duel's focused cards are discarded from.
    FOCUS = "focus"
    # Either of a seat's banish piles.
    BANISH = "banish"


# The location each keyed zone is, for every role a zone can have.
_ROLE_LOCATIONS: dict[ZoneRole, CardLocation] = {
    ZoneRole.HAND: CardLocation.HAND,
    ZoneRole.PROVINCE: CardLocation.PROVINCE,
    ZoneRole.RULEBOOK: CardLocation.RULEBOOK,
    ZoneRole.FATE_DISCARD: CardLocation.DISCARD,
    ZoneRole.DYNASTY_DISCARD: CardLocation.DISCARD,
    ZoneRole.FOCUS: CardLocation.FOCUS,
    ZoneRole.FATE_BANISH: CardLocation.BANISH,
    ZoneRole.DYNASTY_BANISH: CardLocation.BANISH,
}


def location_holding(table: TableState, card: L5RCard) -> CardLocation | None:
    """The location ``card`` is in, or None for a card in none, as one announced from hand is
    while it waits to resolve."""
    if any(held is card for held in table.battlefield.cards):
        return CardLocation.BATTLEFIELD
    for key, zone in table.zones.items():
        if any(held is card for held in zone.cards):
            return _ROLE_LOCATIONS[key.role]
    if any(held is card for deck in table.decks.values() for held in deck.cards):
        return CardLocation.DECK
    return None

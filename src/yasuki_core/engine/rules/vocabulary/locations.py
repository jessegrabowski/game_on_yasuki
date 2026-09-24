from enum import Enum


class CardLocation(str, Enum):
    """Where a card must be for its behavior to be offered, or for its trigger to be collected.
    Distinct from ``ZoneRole``, which cannot name the battlefield, since that is a field of its own
    on the table, not a keyed zone."""

    BATTLEFIELD = "battlefield"
    PROVINCE = "province"
    HAND = "hand"
    # A seat's rulebook zone, where a proxy card stands for abilities the rules give every player.
    RULEBOOK = "rulebook"

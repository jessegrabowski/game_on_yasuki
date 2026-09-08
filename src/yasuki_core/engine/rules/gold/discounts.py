from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# A recruit-discount handler computes the gold reduction on recruiting a card, from the card being
# recruited, the game, and the seat recruiting it. It reduces the card's own cost — the "enters play
# for N less Gold" holdings, gated on a readable condition.
DiscountHandler = Callable[[L5RCard, GameState, PlayerId], int]
RECRUIT_DISCOUNTS: dict[str, DiscountHandler] = {}


def recruit_discount(printed_id: str) -> Callable[[DiscountHandler], DiscountHandler]:
    """Register the decorated function as the recruit-discount handler for ``printed_id``."""

    def register(handler: DiscountHandler) -> DiscountHandler:
        if printed_id in RECRUIT_DISCOUNTS:
            raise ValueError(f"{printed_id} already has a recruit discount")
        RECRUIT_DISCOUNTS[printed_id] = handler
        return handler

    return register


def effective_recruit_discount(game: GameState, card: L5RCard) -> int:
    """The gold ``card`` costs less to recruit from its own conditional cost-reduction ability, or 0
    when it has none."""
    handler = RECRUIT_DISCOUNTS.get(card.printed_id)
    if handler is None:
        return 0
    return handler(card, game, card.owner)


# The same shape one step along: a reduction on a card's Invest rather than on its Gold Cost, for
# the "Invest :g2:, or :g0: if ..." a card prints.
INVEST_DISCOUNTS: dict[str, DiscountHandler] = {}


def invest_discount(printed_id: str) -> Callable[[DiscountHandler], DiscountHandler]:
    """Register the decorated function as the Invest-discount handler for ``printed_id``."""

    def register(handler: DiscountHandler) -> DiscountHandler:
        if printed_id in INVEST_DISCOUNTS:
            raise ValueError(f"{printed_id} already has an invest discount")
        INVEST_DISCOUNTS[printed_id] = handler
        return handler

    return register


def effective_invest_discount(game: GameState, card: L5RCard) -> int:
    """The gold ``card``'s Invest costs less from its own conditional reduction, or 0 with none."""
    handler = INVEST_DISCOUNTS.get(card.printed_id)
    if handler is None:
        return 0
    return handler(card, game, card.owner)

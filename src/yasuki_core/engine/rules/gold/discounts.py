from yasuki_core.engine.registrar import HandlerRegistry
from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# A recruit-discount handler computes the gold reduction on recruiting a card, from the card being
# recruited, the game, and the seat recruiting it. It reduces the card's own cost — the "enters play
# for N less Gold" holdings, gated on a readable condition.
DiscountHandler = Callable[[L5RCard, GameState, PlayerId], int]
RECRUIT_DISCOUNTS: HandlerRegistry[DiscountHandler] = HandlerRegistry(
    "recruit discounts", "already has a recruit discount"
)
recruit_discount = RECRUIT_DISCOUNTS.make_decorator()


def effective_recruit_discount(game: GameState, card: L5RCard) -> int:
    """The gold ``card`` costs less to recruit from its own conditional cost-reduction ability, or 0
    when it has none."""
    handler = RECRUIT_DISCOUNTS.get(card.printed_id)
    if handler is None:
        return 0
    return handler(card, game, card.owner)


# The same shape one step along: a reduction on a card's Invest rather than on its Gold Cost, for
# the "Invest :g2:, or :g0: if ..." a card prints.
INVEST_DISCOUNTS: HandlerRegistry[DiscountHandler] = HandlerRegistry(
    "invest discounts", "already has an invest discount"
)
invest_discount = INVEST_DISCOUNTS.make_decorator()


def effective_invest_discount(game: GameState, card: L5RCard) -> int:
    """The gold ``card``'s Invest costs less from its own conditional reduction, or 0 with none."""
    handler = INVEST_DISCOUNTS.get(card.printed_id)
    if handler is None:
        return 0
    return handler(card, game, card.owner)

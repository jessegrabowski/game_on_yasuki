from yasuki_core.engine.registrar import HandlerRegistry
from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.gold.cost import effective_gold_cost
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard


# A recruit-discount handler computes the gold reduction on recruiting a card, from the card being
# recruited, the game, and the seat recruiting it. It reduces the card's own cost, which is
# what the "enters play for N less Gold" holdings are, gated on a readable condition.
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


# An action-discount handler lowers the Gold its controller pays for an action or a card, from the
# game, the card granting it, the card being paid for, and the keywords the payment answers to. It
# is the "you pay N less for X" a card in play grants its controller, as against a card's own
# conditional reduction above.
ActionDiscountHandler = Callable[[GameState, L5RCard, L5RCard, frozenset[str]], int]
ACTION_DISCOUNTS: HandlerRegistry[ActionDiscountHandler] = HandlerRegistry(
    "action discounts", "already has an action discount"
)
action_discount = ACTION_DISCOUNTS.make_decorator()


def effective_action_discount(
    game: GameState, paid_for: L5RCard, ability_keywords: frozenset[str] = frozenset()
) -> int:
    """The Gold ``paid_for``'s controller pays less for it, summed over every card they control
    that grants a discount.

    The keywords the payment answers to are the ability's own and the card's: an iconised keyword
    on a card bleeds down to every action on it (ShE datasheet, Iconised Keywords). Printed and
    iconised keywords are not told apart in the card data, so every card keyword bleeds down.
    """
    keywords = ability_keywords | frozenset(effective_keywords(game, paid_for))
    return sum(
        handler(game, granter, paid_for, keywords)
        for granter in game.table.battlefield.cards
        if granter.owner is paid_for.owner
        and (handler := ACTION_DISCOUNTS.get(granter.printed_id)) is not None
    )


def discounted_gold(
    game: GameState,
    paid_for: L5RCard,
    amount: int,
    ability_keywords: frozenset[str] = frozenset(),
) -> int:
    """``amount`` less the discounts ``paid_for``'s controller has on it, floored at zero."""
    return max(0, amount - effective_action_discount(game, paid_for, ability_keywords))


def discounted_gold_cost(
    game: GameState, card: L5RCard, ability_keywords: frozenset[str] = frozenset()
) -> int:
    """What ``card``'s controller pays for its Gold Cost: the cost less their discounts on it."""
    return discounted_gold(game, card, effective_gold_cost(game, card), ability_keywords)


def unspent_action_discount(
    game: GameState, card: L5RCard, ability_keywords: frozenset[str] = frozenset()
) -> int:
    """The discount left for the Gold ``card``'s ability charges in its own cost.

    A discount is taken once per action. A card acting from its owner's hand is being played, and
    playing it has already paid its Gold Cost, which took its share of the discount first.
    """
    discount = effective_action_discount(game, card, ability_keywords)
    if card in game.table.zones[ZoneKey(card.owner, ZoneRole.HAND)].cards:
        discount -= min(discount, effective_gold_cost(game, card))
    return discount

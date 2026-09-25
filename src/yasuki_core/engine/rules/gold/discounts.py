from yasuki_core.engine.registrar import HandlerRegistry
from collections.abc import Callable
from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.gold.cost import effective_gold_cost
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
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


@dataclass(frozen=True, slots=True)
class Purchase:
    """A Gold payment as an action discount reads it: who pays, and for what.

    Attributes
    ----------
    seat : PlayerId
        The seat paying.
    card : L5RCard or None
        The card whose Gold Cost or ability the payment is for, or None for a player ability,
        which is no card's action even when it names a card, as Kharmic names the card it
        discards (CR, Kharmic).
    keywords : frozenset of str
        The action's keywords: the ability's own, and the card's when the ability is the card's,
        since keywords on a card apply to its abilities (ShE datasheet).
    plays_card : bool
        Whether the action plays the card and so pays its Gold Cost, as a Strategy from hand or an
        Equip does.
    """

    seat: PlayerId
    card: L5RCard | None
    keywords: frozenset[str]
    plays_card: bool


def card_purchase(game: GameState, card: L5RCard, *, plays_card: bool) -> Purchase:
    """A payment for an Interrupt ``card`` prints, which is the card's own action and carries its
    keywords."""
    return Purchase(
        seat=card.owner,
        card=card,
        keywords=frozenset(effective_keywords(game, card)),
        plays_card=plays_card,
    )


def equip_purchase(card: L5RCard) -> Purchase:
    """A payment to Equip ``card``. Equip is a player ability the rulebook grants (CR, Player
    Abilities and Traits), so it carries none of the card's keywords, though it pays for the
    card."""
    return Purchase(seat=card.owner, card=card, keywords=frozenset(), plays_card=True)


# An action-discount handler lowers the Gold its controller pays, from the game, the card granting
# the discount, and the purchase. It is the "you pay N less for X" a card in play grants its
# controller, as against a card's own conditional reduction above.
ActionDiscountHandler = Callable[[GameState, L5RCard, Purchase], int]
ACTION_DISCOUNTS: HandlerRegistry[ActionDiscountHandler] = HandlerRegistry(
    "action discounts", "already has an action discount"
)
action_discount = ACTION_DISCOUNTS.make_decorator()


def effective_action_discount(game: GameState, purchase: Purchase) -> int:
    """The Gold ``purchase``'s seat pays less for it, summed over every card they control that
    grants a discount."""
    return sum(
        handler(game, granter, purchase)
        for granter in game.table.battlefield.cards
        if granter.owner is purchase.seat
        and (handler := ACTION_DISCOUNTS.get(granter.printed_id)) is not None
    )


def discounted_gold(game: GameState, purchase: Purchase, amount: int) -> int:
    """``amount`` less the discounts ``purchase``'s seat has on it, floored at zero."""
    return max(0, amount - effective_action_discount(game, purchase))


def discounted_gold_cost(game: GameState, purchase: Purchase) -> int:
    """What ``purchase``'s seat pays for its card's Gold Cost, less their discounts on it.

    Raise ValueError for a player ability's purchase, which has no card whose Gold Cost is paid.
    """
    if purchase.card is None:
        raise ValueError("a player ability pays no card's Gold Cost")
    return discounted_gold(game, purchase, effective_gold_cost(game, purchase.card))


def unspent_action_discount(game: GameState, purchase: Purchase) -> int:
    """The discount left for the Gold an ability charges in its own cost.

    A discount is taken once per action, and an action that plays its card has already paid the
    card's Gold Cost, which took its share of the discount first.
    """
    discount = effective_action_discount(game, purchase)
    if purchase.plays_card and purchase.card is not None:
        discount -= min(discount, effective_gold_cost(game, purchase.card))
    return discount

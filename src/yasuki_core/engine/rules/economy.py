from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.stats.calculation import active_modifiers, effective_stat
from yasuki_core.engine.rules.modifiers import (
    Stat,
)
from yasuki_core.engine.rules.state import GameState, used_this_turn
from yasuki_core.engine.table import unit_members
from yasuki_core.game_pieces.cards import L5RCard


# A gold-production handler computes what a card produces in context, from the producing card, the
# game, the seat it produces for, and the cards being paid for.
GoldHandler = Callable[[L5RCard, GameState, PlayerId, tuple[L5RCard, ...]], int]
GOLD_HANDLERS: dict[str, GoldHandler] = {}


def gold_handler(printed_id: str) -> Callable[[GoldHandler], GoldHandler]:
    """Register the decorated function as the gold-production handler for ``printed_id``."""

    def register(handler: GoldHandler) -> GoldHandler:
        # Assignment would let the second registration shadow the first with no trace; by the time
        # anything inspects the registry only the survivor is there.
        if printed_id in GOLD_HANDLERS:
            raise ValueError(f"{printed_id} already has a gold handler")
        GOLD_HANDLERS[printed_id] = handler
        return handler

    return register


def unit_gold_cost(game: GameState, personality: L5RCard) -> int:
    """A unit's total Gold Cost: the Personality's own and every card attached to him (CR, Unit).

    What a card means by "his unit's cost" — the pool a variable-cost action is priced against.
    """
    return sum(
        effective_gold_cost(game, member) for member in unit_members(game.table, personality)
    )


def effective_gold_cost(game: GameState, card: L5RCard) -> int:
    """What ``card`` costs before the seat's own discounts and surcharges: its printed gold cost plus
    every active Gold Cost modifier on it, floored at zero. A card printing no gold cost has none to
    modify, so it stays at zero (CR, Absent Stats).

    Parameters
    ----------
    game : GameState
        The live game the modifiers are read from.
    card : L5RCard
        The card being priced.

    Returns
    -------
    cost : int
        The modified gold cost.
    """
    return effective_stat(game, card, Stat.GOLD_COST)


def effective_gold_production(
    game: GameState, card: L5RCard, targets: tuple[L5RCard, ...] = ()
) -> int:
    """The gold ``card`` produces right now: its registered handler's result against the live views,
    or its printed ``gold_production`` when no handler is registered, plus every active Gold
    Production modifier on it (wealth counters, ability grants), floored at zero. A card with no
    Gold Production stat produces 0 and receives no modifiers (the stat is absent).

    Parameters
    ----------
    game : GameState
        The live game the views project from.
    card : L5RCard
        The producing card.
    targets : tuple of L5RCard, optional
        The cards being paid for, for a handler whose yield depends on what it pays for. Default
        empty.
    """
    handler = GOLD_HANDLERS.get(card.printed_id)
    if handler is None:
        if not hasattr(card, "gold_production"):
            return 0  # an absent stat cannot receive modifiers (CR, Absent Stats)
        base = card.gold_production
    else:
        base = handler(card, game, card.owner, targets)
    total = base + sum(
        modifier.amount for modifier in active_modifiers(game, card, Stat.GOLD_PRODUCTION)
    )
    return max(0, total)


# What a card can grant its own Gold Production as it bows, computed from the card and its
# controller's and opponents' views. A delta over whatever the card is worth at the time rather than
# a total: counters and granted modifiers feed the same stat, so a flat ceiling would under-report
# the moment anything else raised the card. A handler rather than a number because a card may gate
# its grant on a condition — Slave Pits offers nothing to the player who went first — and a grant
# affordability counts but the card refuses would strand the payment it made reachable.
SelfGrantHandler = Callable[[L5RCard, GameState, PlayerId], int]
GOLD_SELF_GRANT: dict[str, SelfGrantHandler] = {}

# The once-per-turn tag a card claims as it grants itself. Read here to tell a grant still to come
# from one `effective_gold_production` is already carrying, and by the trait that prices it.
SELF_GRANT = "gold_self_grant"


def self_grant(printed_id: str) -> Callable[[SelfGrantHandler], SelfGrantHandler]:
    """Register the decorated function as ``printed_id``'s self-grant, for a card whose own
    conditions decide how much it offers, or whether it offers anything at all."""

    def register(handler: SelfGrantHandler) -> SelfGrantHandler:
        if printed_id in GOLD_SELF_GRANT:
            raise ValueError(f"{printed_id} already grants itself Gold Production")
        GOLD_SELF_GRANT[printed_id] = handler
        return handler

    return register


def register_self_grant(printed_id: str, amount: int) -> None:
    """Declare that ``printed_id`` may raise its own Gold Production by ``amount`` as it bows.

    What the card's window trigger grants, told to affordability separately so a purchase only the
    grant can reach is still offered. The trigger is what makes the grant happen; this is what makes
    it countable before anyone is asked. Use :func:`self_grant` for a card that offers its grant only
    under a condition.
    """
    self_grant(printed_id)(lambda card, me, opponents: amount)


def maximum_gold_production(
    game: GameState, card: L5RCard, targets: tuple[L5RCard, ...] = ()
) -> int:
    """The most ``card`` could yield if its controller took every option it offers.

    What affordability asks, so that a purchase reachable only by a card raising its own yield is
    still offered. :func:`effective_gold_production` answers the same question for right now.

    A card that has already granted itself this turn adds nothing more: the grant is inside
    :func:`effective_gold_production` by then, and counting it twice would report a ceiling the card
    cannot reach.

    Two other places measure a seat's gold and deliberately report less: ``policies._spendable`` and
    :func:`~yasuki_core.sim.metrics.potential_gold_production` both leave a self-grant out, because
    weighing whether a purchase is worth making is not the same question as whether it is legal.

    Parameters
    ----------
    game : GameState
        The live game the views project from.
    card : L5RCard
        The producing card.
    targets : tuple of L5RCard, optional
        The cards being paid for, for a handler whose yield depends on what it pays for. Default
        empty.
    """
    return effective_gold_production(game, card, targets) + untaken_self_grant(game, card)


def untaken_self_grant(game: GameState, card: L5RCard) -> int:
    """What ``card`` can still grant itself this turn, or nothing once it has or its card declines
    to offer under current conditions."""
    handler = GOLD_SELF_GRANT.get(card.printed_id)
    if handler is None or used_this_turn(game, card, SELF_GRANT):
        return 0
    return handler(card, game, card.owner)


# A recruit-discount handler computes the gold reduction on recruiting a card, from the card being
# recruited and its controller's and opponents' views. It reduces the card's own cost — the "enters
# play for N less Gold" holdings, gated on a readable condition.
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

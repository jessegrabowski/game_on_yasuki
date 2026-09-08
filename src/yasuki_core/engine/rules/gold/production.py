from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.calculation import active_modifiers
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


def reads_its_targets(card: L5RCard) -> bool:
    """Whether ``card``'s yield can depend on what it is paying for, which only a registered handler
    is given the chance to read."""
    return card.printed_id in GOLD_HANDLERS


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

    Returns
    -------
    produced : int
        The gold the card yields now.
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

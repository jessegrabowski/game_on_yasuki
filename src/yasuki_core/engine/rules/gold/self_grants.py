from yasuki_core.engine.registrar import HandlerRegistry
from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.gold.production import effective_gold_production
from yasuki_core.engine.rules.state import GameState, used_this_turn
from yasuki_core.game_pieces.cards import L5RCard


# What a card can grant its own Gold Production as it bows, computed from the card, the game, and
# the seat it produces for. A delta over whatever the card is worth at the time rather than
# a total: counters and granted modifiers feed the same stat, so a flat ceiling would under-report
# the moment anything else raised the card. A handler rather than a number because a card may gate
# its grant on a condition — Slave Pits offers nothing to the player who went first — and a grant
# affordability counts but the card refuses would strand the payment it made reachable.
SelfGrantHandler = Callable[[L5RCard, GameState, PlayerId], int]
GOLD_SELF_GRANT: HandlerRegistry[SelfGrantHandler] = HandlerRegistry(
    "gold self grants", "already grants itself Gold Production"
)
self_grant = GOLD_SELF_GRANT.make_decorator()

# The once-per-turn tag a card claims as it grants itself. Read here to tell a grant still to come
# from one `effective_gold_production` is already carrying, and by the trait that prices it.
SELF_GRANT = "gold_self_grant"


def register_self_grant(printed_id: str, amount: int) -> None:
    """Declare that ``printed_id`` may raise its own Gold Production by ``amount`` as it bows.

    What the card's window trigger grants, told to affordability separately so a purchase only the
    grant can reach is still offered. The trigger is what makes the grant happen; this is what makes
    it countable before anyone is asked. Use :func:`self_grant` for a card that offers its grant only
    under a condition.
    """
    self_grant(printed_id)(lambda card, game_, seat: amount)


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

    Returns
    -------
    ceiling : int
        The most the card could yield.
    """
    return effective_gold_production(game, card, targets) + untaken_self_grant(game, card)


def untaken_self_grant(game: GameState, card: L5RCard) -> int:
    """What ``card`` can still grant itself this turn, or nothing once it has or its card declines
    to offer under current conditions."""
    handler = GOLD_SELF_GRANT.get(card.printed_id)
    if handler is None or used_this_turn(game, card, SELF_GRANT):
        return 0
    return handler(card, game, card.owner)

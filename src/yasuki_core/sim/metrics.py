from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.economy import effective_gold_production
from yasuki_core.engine.rules.flow import gold_producers
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import ZoneRole

# A metric answers one question about one seat at one moment.
Metric = Callable[[GameState, PlayerId], int]


def potential_gold_production(game: GameState, seat: PlayerId) -> int:
    """
    What ``seat``'s straight producers yield at no cost, right now.

    Computed rather than read: ``game.gold`` is a transient pool, filled during a payment and
    cleared at the end of the phase, so it reads zero at every turn boundary.

    Two things are deliberately outside this number, and both make it smaller than
    :func:`~yasuki_core.engine.rules.flow.reachable_gold` for the same board.

    A bow-time boost is excluded, because taking one has a price the card sets — Outlying Farms
    destroys itself — so counting it would report gold a seat may rationally decline. This measures
    sustainable output, which is what a deck is being judged on.

    A producer's yield can depend on what it pays for (Jade Works yields more against a Jade card),
    and a metric has no payment in flight, so such a producer reports its unconditional base.
    """
    return sum(effective_gold_production(game, card) for card in gold_producers(game, seat))


def family_honor(game: GameState, seat: PlayerId) -> int:
    """
    ``seat``'s Family Honor.

    Read directly rather than computed: honor is a standing total set from the stronghold and sensei
    at setup and moved by effects since, so unlike the gold pool it means the same thing at any
    moment. It can go negative, which is a real position rather than an error.
    """
    return game.table.seats[seat].honor


def empty_provinces(game: GameState, seat: PlayerId) -> int:
    """
    How many of ``seat``'s provinces hold no card.

    A province refills from the dynasty deck as it empties, so this counts only those it could not
    refill — the seat has recruited or discarded faster than its deck can replace.
    """
    return sum(
        1
        for key, zone in game.table.zones.items()
        if key.owner is seat and key.role is ZoneRole.PROVINCE and not zone.cards
    )

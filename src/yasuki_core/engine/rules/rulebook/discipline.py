from collections.abc import Callable
from dataclasses import replace
from enum import Enum, auto

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.registrar import HandlerRegistry
from yasuki_core.engine.rules.gold.discounts import Purchase
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.locations import CardLocation
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard

# Cards printing Discipline, by printed id, each with the Gold its Discipline costs right now, or
# None while a condition withholds it: "Discipline :g2:", or "If you are a Crab Clan player, this
# Strategy has Discipline :g1:". A player may play such a card from their own discard pile for one
# of its actions, adding that Gold to the action's Gold cost, and the card is removed from the game
# once the action ends (CR, Discipline).
DisciplineCost = Callable[[GameState, L5RCard], int | None]
DISCIPLINES: HandlerRegistry[DisciplineCost] = HandlerRegistry(
    "disciplines", "already prints a Discipline"
)
register_discipline = DISCIPLINES.make_register()

# Cards in play giving Discipline to cards in their controller's discard pile, by printed id, each
# mapping ``(game, granting card, card in the pile)`` to the Gold of the Discipline it gives that
# card, or None for a card it gives none: "Dark Virtues in your discard pile have Discipline :g2:".
DisciplineGrant = Callable[[GameState, L5RCard, L5RCard], int | None]
DISCIPLINE_GRANTS: HandlerRegistry[DisciplineGrant] = HandlerRegistry(
    "discipline grants", "already gives cards Discipline"
)
discipline_grant = DISCIPLINE_GRANTS.make_decorator()


class Reach(Enum):
    """How an ability or Interrupt is taken from where its card sits."""

    ACTIVATED = auto()
    PLAYED = auto()
    PLAYED_UNDER_DISCIPLINE = auto()


def disciplined(amount: int) -> DisciplineCost:
    """The Discipline cost of a card printing "Discipline :g``amount``:" with no condition."""

    def cost(game: GameState, card: L5RCard) -> int:
        return amount

    return cost


def discipline_cost(game: GameState, card: L5RCard) -> int | None:
    """The Gold ``card``'s Discipline costs, the least of what it prints and what the cards its
    owner controls give it, or None when it has no Discipline."""
    printed = DISCIPLINES.get(card.printed_id)
    costs = [] if printed is None else [printed(game, card)]
    costs.extend(
        grant(game, granter, card) for granter, grant in discipline_granters(game, card.owner)
    )
    return min((cost for cost in costs if cost is not None), default=None)


def discipline_granters(game: GameState, seat: PlayerId) -> list[tuple[L5RCard, DisciplineGrant]]:
    """The cards ``seat`` controls that give cards in its discard pile Discipline, each with its
    grant."""
    return [
        (card, grant)
        for card in game.table.battlefield.cards
        if card.owner is seat and (grant := DISCIPLINE_GRANTS.get(card.printed_id)) is not None
    ]


def may_have_discipline(card: L5RCard, *, granted: bool) -> bool:
    """Whether ``card`` could have Discipline: it prints one, or a card its owner controls gives
    some, as ``granted`` says. What a pass over a discard pile asks before pricing anything."""
    return granted or card.printed_id in DISCIPLINES


def in_discard_pile(game: GameState, card: L5RCard) -> bool:
    """Whether ``card`` is in its owner's Fate discard pile, the one a Strategy is played from."""
    pile = game.table.zones[ZoneKey(card.owner, ZoneRole.FATE_DISCARD)]
    return any(held is card for held in pile.cards)


def reach(
    game: GameState,
    location: CardLocation,
    card: L5RCard,
    located_at: tuple[CardLocation, ...],
    *,
    from_rulebook: bool,
) -> Reach | None:
    """How an ability or Interrupt acting from ``located_at`` is taken on ``card`` sitting at
    ``location``, or None when it is not offered there.

    The card's own action out of the hand is played. So is one out of its owner's Fate discard
    pile while the card has Discipline (CR, Discipline). Anything else acting from where the card
    sits is activated, and one the rulebook confers is always activated, paying its own cost (CR,
    Kharmic).
    """
    if location in located_at:
        played = location is CardLocation.HAND and not from_rulebook
        return Reach.PLAYED if played else Reach.ACTIVATED
    if (
        location is CardLocation.DISCARD
        and CardLocation.HAND in located_at
        and not from_rulebook
        and in_discard_pile(game, card)
        and discipline_cost(game, card) is not None
    ):
        return Reach.PLAYED_UNDER_DISCIPLINE
    return None


def under_discipline(game: GameState, purchase: Purchase) -> Purchase:
    """``purchase``, the playing of its card, with the card's Discipline added to its Gold Cost
    (CR, Discipline). Raise ValueError for a card without Discipline."""
    if purchase.card is None:
        raise ValueError("a player ability plays no card under Discipline")
    cost = discipline_cost(game, purchase.card)
    if cost is None:
        raise ValueError(f"{purchase.card.id} has no Discipline to be played under")
    return replace(purchase, discipline=cost)

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    CardLocation,
    no_cost,
    register_ability,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import (
    Ask,
    Choose,
    Discard,
    Effect,
    MoveToHand,
    Show,
    ShuffleDeck,
    Then,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import RingPrint


# --- Wisdom Gained ---


def _wisdom_gained_findable_rings(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The Rings in ``seat``'s Fate deck and Fate discard pile — both piles the search reaches."""
    piles = (
        game.table.decks[DeckKey(seat, Side.FATE)].cards,
        game.table.zones[ZoneKey(seat, ZoneRole.FATE_DISCARD)].cards,
    )
    return tuple(card.id for pile in piles for card in pile if isinstance(card.printed, RingPrint))


def _wisdom_gained_search_order(game: GameState, controller: PlayerId) -> tuple[PlayerId, ...]:
    """Every seat in the order the card asks them, its controller first."""
    return (controller, *(seat for seat in game.table.seats if seat is not controller))


def _wisdom_gained_ask_to_search(
    game: GameState, event_id: str, seats: tuple[PlayerId, ...]
) -> list[Effect]:
    """Put the offer to the first of ``seats`` holding a Ring. A seat with none is passed over rather
    than asked a question it cannot answer, and each answer asks the seat behind it — so the offer
    moves along one player at a time in the order the card names."""
    for seat in seats:
        if _wisdom_gained_findable_rings(game, seat):
            question = "Search your discard pile and Fate deck for a Ring?"
            return [
                Ask(
                    seat,
                    question,
                    "wisdom_gained_search",
                    subjects=(event_id,),
                    source_id=event_id,
                )
            ]
    return []


def _wisdom_gained_seats_behind(
    game: GameState, event_id: str, seat: PlayerId
) -> tuple[PlayerId, ...]:
    """The seats still to be offered the search after ``seat`` has answered."""
    order = _wisdom_gained_search_order(game, game.table.cards_by_id[event_id].owner)
    return order[order.index(seat) + 1 :]


@choice_resolver("wisdom_gained_search")
def _resolve_wisdom_gained_search(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Open the search for a seat that accepted, or pass the offer on. The offer comes before the
    search rather than after it because searching is what costs the shuffle — a seat that would
    rather keep the order of its deck has to be able to decline without looking."""
    if not chosen:
        return _wisdom_gained_ask_to_search(
            game, source_id, _wisdom_gained_seats_behind(game, source_id, seat)
        )
    rings = _wisdom_gained_findable_rings(game, seat)
    return [Choose(seat, rings, 1, 1, "wisdom_gained_ring", source_id)]


@choice_resolver("wisdom_gained_ring", prompt="Take a Ring into your hand")
def _resolve_wisdom_gained_ring(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Take the Ring, shuffle the deck the search read, then offer it to the seats behind."""
    return [
        Show(chosen[0]),
        MoveToHand(chosen[0], seat),
        ShuffleDeck(DeckKey(seat, Side.FATE)),
        *_wisdom_gained_ask_to_search(
            game, source_id, _wisdom_gained_seats_behind(game, source_id, seat)
        ),
    ]


def _wisdom_gained_targets(game: GameState, card: L5RCard) -> list[str]:
    """The Event itself. Every seat searches, so the ability names no card to act on."""
    return [card.id]


def _wisdom_gained_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Spend the Event, then let each seat search in turn, starting with its controller."""
    seat = source.owner
    order = _wisdom_gained_search_order(game, seat)
    return [
        Discard(source.id, seat),
        Then(tuple(_wisdom_gained_ask_to_search(game, source.id, order))),
    ]


register_ability(
    "wisdom_gained",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Each player may search for a Ring, starting with you",
        cost=no_cost,
        targets=_wisdom_gained_targets,
        effects=_wisdom_gained_effects,
        all_targets=True,
        located_at=(CardLocation.PROVINCE,),
    ),
)

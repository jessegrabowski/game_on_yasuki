from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.model import Ability, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.counts_as import Asking, counts_as
from yasuki_core.engine.rules.board.queries import top_of_deck
from yasuki_core.engine.rules.effects import (
    Choose,
    Destroy,
    DiscardFromHand,
    Effect,
    EndLook,
    LookAtTop,
    MoveToHand,
    PlaceOnDeck,
    Show,
    ShuffleDeck,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import action_did, choice_resolver
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import RingPrint


# --- Plain Library ---

PLAIN_LIBRARY_LOOK = 3
PLAIN_LIBRARY_PLACE = 2


# The Shattered Empire printing. Its earlier printings spell out the Fortification entering play
# bowed and its bow for 3 Gold, which the CR and its printed production now carry.


def _plain_library_targets(game: GameState, source: L5RCard) -> list[str]:
    """Itself, once the action just resolved was the one that Recruited it: the Response is offered
    in the Step that Recruit opens, and the seat takes it or declines, as with Courts of Otosan
    Uchi."""
    if not any(event.card_id == source.id for event in action_did(game, EnteredPlay)):
        return []
    return [source.id]


def _plain_library_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    seat = source.owner
    fate = DeckKey(seat, Side.FATE)
    seen = top_of_deck(game, fate, PLAIN_LIBRARY_LOOK)
    if not seen:
        return []
    return [
        LookAtTop(seat, fate, len(seen)),
        Choose(seat, seen, 0, PLAIN_LIBRARY_PLACE, "plain_library", source.id),
    ]


@choice_resolver("plain_library", prompt="Place zero to two of them at the bottom of your deck")
def _resolve_plain_library(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The cards go under the deck in the order picked, and the rest stay where they are."""
    return [PlaceOnDeck(chosen, DeckKey(seat, Side.FATE), to_bottom=True), EndLook()]


register_ability(
    "plain_library",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        cost=no_cost,
        targets=_plain_library_targets,
        effects=_plain_library_effects,
        hits_every_target=True,
        tireless=True,
    ),
)


# --- Remote Temple ---


def _remote_temple_rings(game: GameState, source: L5RCard) -> tuple[str, ...]:
    asking = Asking.action(source)
    deck = game.table.decks[DeckKey(source.owner, Side.FATE)].cards
    return tuple(card.id for card in deck if counts_as(game, card, RingPrint, asking))


def _remote_temple_after_search(seat: PlayerId, source_id: str) -> list[Effect]:
    """The searched deck is shuffled (CR, Search), then "Discard a card. Destroy this Holding." """
    return [
        ShuffleDeck(DeckKey(seat, Side.FATE)),
        DiscardFromHand(seat, 1, seat, seat),
        Destroy(source_id, seat),
    ]


def _remote_temple_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """A deck holding no Ring is still searched, so the rest of the text resolves without one."""
    rings = _remote_temple_rings(game, source)
    if not rings:
        return _remote_temple_after_search(source.owner, source.id)
    return [Choose(source.owner, rings, 1, 1, "remote_temple", source.id)]


@choice_resolver("remote_temple", prompt="Take a Ring into your hand")
def _resolve_remote_temple(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [
        Show(chosen[0]),
        MoveToHand(chosen[0], seat),
        *_remote_temple_after_search(seat, source_id),
    ]


register_ability(
    "remote_temple",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=itself,
        hits_every_target=True,
        effects=_remote_temple_effects,
    ),
)

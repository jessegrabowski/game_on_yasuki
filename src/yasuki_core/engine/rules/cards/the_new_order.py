from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import top_of_deck
from yasuki_core.engine.rules.effects import Choose, Effect, EndLook, LookAtTop, PlaceOnDeck
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import action_did, choice_resolver
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


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

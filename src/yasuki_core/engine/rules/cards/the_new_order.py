from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.registry import EntryState, entry_state
from yasuki_core.engine.rules.board.queries import top_of_deck
from yasuki_core.engine.rules.effects import Choose, Effect, EndLook, LookAtTop, PlaceOnDeck
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


# --- Plain Library ---

PLAIN_LIBRARY_LOOK = 3
PLAIN_LIBRARY_PLACE = 2


@entry_state("plain_library")
def _plain_library_entry_state(game: GameState, card: L5RCard) -> EntryState:
    """ "This Fortification enters play bowed." Its bow for 3 Gold is printed production."""
    return EntryState(bowed=True)


@on(EnteredPlay, "plain_library")
def _plain_library_entered_play(ctx: TriggerContext) -> list[Effect]:
    """ "Interrupt: After you Recruit this Holding, look at the top three cards of your Fate deck.
    Place zero to two of them at the bottom of your deck." Modeled as a reaction to its own entry,
    which is where the engine puts a card's after-Recruit text."""
    if ctx.event.card_id != ctx.card.id:
        return []
    seat = ctx.card.owner
    fate = DeckKey(seat, Side.FATE)
    seen = top_of_deck(ctx.game, fate, PLAIN_LIBRARY_LOOK)
    if not seen:
        return []
    return [
        LookAtTop(seat, fate, len(seen)),
        Choose(seat, seen, 0, PLAIN_LIBRARY_PLACE, "plain_library", ctx.card.id),
    ]


@choice_resolver("plain_library", prompt="Place zero to two of them at the bottom of your deck")
def _resolve_plain_library(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The cards go under the deck in the order picked, and the rest stay where they are."""
    return [PlaceOnDeck(chosen, DeckKey(seat, Side.FATE), to_bottom=True), EndLook()]

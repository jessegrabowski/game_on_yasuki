from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import Effect, EndLook, MoveToHand, PlaceOnDeck, ShuffleDeck
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.vocabulary.looks import Look

# The endings a look has often enough to register once, so a card names one rather than writing
# its own. Each closes the look.
PUT_BACK_ON_TOP = "put_back_on_top"
PUT_ON_BOTTOM = "put_on_bottom"
TAKE_ONE_AND_SHUFFLE = "take_one_and_shuffle"


def _open_look(game: GameState) -> Look:
    look = game.look
    if look is None:
        raise ValueError("no look is open to put cards back from")
    return look


@choice_resolver(PUT_BACK_ON_TOP, prompt="Put the rest back in any order")
def _put_back_on_top(
    game: GameState, source_id: str | None, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [PlaceOnDeck(chosen, _open_look(game).deck), EndLook()]


@choice_resolver(PUT_ON_BOTTOM, prompt="Put them on the bottom of your deck in any order")
def _put_on_bottom(
    game: GameState, source_id: str | None, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [PlaceOnDeck(chosen, _open_look(game).deck, to_bottom=True), EndLook()]


@choice_resolver(TAKE_ONE_AND_SHUFFLE, prompt="Put one in your hand")
def _take_one_and_shuffle(
    game: GameState, source_id: str | None, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """ "Put one in your hand. Shuffle the deck." The look closes before the shuffle, which would
    otherwise leave it naming cards that have moved."""
    deck = _open_look(game).deck
    return [MoveToHand(chosen[0], seat), EndLook(), ShuffleDeck(deck)]

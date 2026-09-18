from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import Effect, EndLook, PlaceOnDeck
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.vocabulary.looks import Look

# The two endings a look has when a card says "in any order", registered once so a card names one
# rather than writing its own. Each puts the cards where the seat ordered them and closes the look.
PUT_BACK_ON_TOP = "put_back_on_top"
PUT_ON_BOTTOM = "put_on_bottom"


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

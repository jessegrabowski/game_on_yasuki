from yasuki_core.engine.rules.modifiers import Duration, Ongoing
from yasuki_core.engine.rules.state import GameState


def _on_battlefield(game: GameState, card_id: str) -> bool:
    return any(card.id == card_id for card in game.table.battlefield.cards)


def grant_applies(game: GameState, recorded: Ongoing) -> bool:
    """Whether a recorded ongoing effect is in force — a ``WHILE_SOURCE_IN_PLAY`` one only while
    the card it came from is still on the battlefield."""
    return recorded.duration is not Duration.WHILE_SOURCE_IN_PLAY or _on_battlefield(
        game, recorded.source_id
    )

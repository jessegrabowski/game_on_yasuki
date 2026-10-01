from yasuki_core.engine.rules.vocabulary.modifiers import DuelStatOverride, Duration, Ongoing, Stat
from yasuki_core.engine.rules.state import GameState


def _on_battlefield(game: GameState, card_id: str) -> bool:
    return any(card.id == card_id for card in game.table.battlefield.cards)


def grant_applies(game: GameState, recorded: Ongoing) -> bool:
    """Whether a recorded ongoing effect is in force. A ``WHILE_SOURCE_IN_PLAY`` one only while
    the card it came from is still on the battlefield."""
    return recorded.duration is not Duration.WHILE_SOURCE_IN_PLAY or _on_battlefield(
        game, recorded.source_id
    )


def named_duel_stat(game: GameState, card_id: str) -> Stat | None:
    """The stat a card has been told its duels compare, or None where nothing has told it (CR, Duel
    Stat). The last override in force wins, since a later effect replaces an earlier one."""
    return next(
        (
            held.stat
            for held in reversed(game.ongoing)
            if isinstance(held, DuelStatOverride)
            and held.target_id == card_id
            and grant_applies(game, held)
        ),
        None,
    )

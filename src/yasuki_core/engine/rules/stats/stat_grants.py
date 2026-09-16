from collections.abc import Callable, Iterator

from yasuki_core.engine.registrar import HandlerRegistry
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.game_pieces.cards import L5RCard


# What a card in play gives a card for a stat by its own text, read off the board on every stat
# read and gone the moment the granting card leaves play. The handler decides whom it reaches:
# itself ("While opposed, Tashiko has a Force bonus..."), the Personality it hangs on ("This
# Personality has +1PH"), or any card the text names. Keyed by printed id like the other per-card
# registries.
StatGrantHandler = Callable[[GameState, L5RCard, L5RCard, Stat], int]
STAT_GRANTS: HandlerRegistry[StatGrantHandler] = HandlerRegistry(
    "stat grants", "already has a stat grant"
)
stat_grant = STAT_GRANTS.make_decorator()


def granted_stats(game: GameState, card: L5RCard, stat: Stat) -> Iterator[tuple[L5RCard, int]]:
    """Each card in play whose text gives ``card`` something for ``stat`` right now, with the
    amount, in play order."""
    for granting in game.table.battlefield.cards:
        handler = STAT_GRANTS.get(granting.printed_id)
        if handler is None:
            continue
        amount = handler(game, granting, card, stat)
        if amount:
            yield granting, amount

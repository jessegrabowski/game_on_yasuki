from collections.abc import Callable, Iterator, Sequence

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


def stat_granters(game: GameState) -> tuple[L5RCard, ...]:
    """The cards in play whose text gives stats, in play order."""
    return tuple(card for card in game.table.battlefield.cards if card.printed_id in STAT_GRANTS)


def granted_stats(
    game: GameState,
    card: L5RCard,
    stat: Stat,
    *,
    granters: Sequence[L5RCard] | None = None,
) -> Iterator[tuple[L5RCard, int]]:
    """Each card in play whose text gives ``card`` something for ``stat`` right now, with the
    amount, in play order.

    Parameters
    ----------
    granters : sequence of L5RCard, optional
        What :func:`stat_granters` returns for this board, for a caller reading many cards against
        one board. Default None, read off the board here.
    """
    for granting in stat_granters(game) if granters is None else granters:
        amount = STAT_GRANTS[granting.printed_id](game, granting, card, stat)
        if amount:
            yield granting, amount

from collections.abc import Callable

from yasuki_core.engine.registrar import HandlerRegistry
from yasuki_core.engine.rules.board.counts_as import Asking
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.calculation import effective_stat
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.game_pieces.cards import L5RCard

# What a card's own text has it considered to have for a stat when a certain asker checks it, as
# "considered to have 3 Chi when a Kiho checks a card's Chi" has it. The handler answers None for
# an asker its text does not name. Keyed by printed id like the other per-card registries.
ConsideredStat = Callable[[GameState, L5RCard, Stat, Asking], int | None]
CONSIDERED_STATS: HandlerRegistry[ConsideredStat] = HandlerRegistry(
    "considered stats", "already has a considered stat"
)
considered_stat = CONSIDERED_STATS.make_decorator()


def checked_stat(game: GameState, card: L5RCard, stat: Stat, asking: Asking) -> int:
    """``card``'s ``stat`` as ``asking`` checks it: what its text has it considered to have for
    that asker, else its effective value."""
    considered = CONSIDERED_STATS.get(card.printed_id)
    if considered is not None:
        value = considered(game, card, stat, asking)
        if value is not None:
            return value
    return effective_stat(game, card, stat)

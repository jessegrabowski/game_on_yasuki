from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import Counter


@dataclass(frozen=True, slots=True)
class TurnStarted:
    """A seat's turn has begun (after straighten and province reveal)."""

    seat: PlayerId


@dataclass(frozen=True, slots=True)
class CardDiscarded:
    """A card entered a discard pile. ``by_seat`` is the seat whose action caused it, ``side`` the
    discarded card's side — the two facts a discard-reaction reads ("your action, a Fate card")."""

    card_id: str
    side: Side
    by_seat: PlayerId


@dataclass(frozen=True, slots=True)
class CounterGained:
    """A card gained ``amount`` of a counter — the actual number added, after any floor."""

    card_id: str
    counter: Counter
    amount: int


GameEvent = TurnStarted | CardDiscarded | CounterGained

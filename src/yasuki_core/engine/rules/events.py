from dataclasses import dataclass

from yasuki_core.engine.players import Cause, PlayerId
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import Counter


@dataclass(frozen=True, slots=True)
class TurnStarted:
    """A seat's turn has begun (after straighten and province reveal)."""

    seat: PlayerId


@dataclass(frozen=True, slots=True)
class CardDiscarded:
    """A card entered a discard pile. ``cause`` is who or what put it there and ``side`` the card's
    side — the two facts a discard-reaction reads ("your action, a Fate card"). A ``Rulebook`` cause
    means no player chose it, so a reaction guarded on a seat correctly ignores it."""

    card_id: str
    side: Side
    cause: Cause


@dataclass(frozen=True, slots=True)
class CounterGained:
    """A card gained ``amount`` of a counter — the actual number added, after any floor."""

    card_id: str
    counter: Counter
    amount: int


@dataclass(frozen=True, slots=True)
class Destroyed:
    """A card was destroyed — sent to a discard by destruction, distinct from being discarded from
    hand. ``cause`` names who or what destroyed it, which cards ask about: several react only to a
    Personality destroyed for having zero Chi, and others only to a destruction that was not their
    own doing."""

    card_id: str
    cause: Cause


@dataclass(frozen=True, slots=True)
class EnteredPlay:
    """A card entered play on the battlefield."""

    card_id: str


@dataclass(frozen=True, slots=True)
class Revealed:
    """A face-down card in a Province was turned face-up. A card that arrives already face-up raises
    nothing — the event names the turn, not the resulting state."""

    card_id: str


GameEvent = TurnStarted | CardDiscarded | CounterGained | Destroyed | EnteredPlay | Revealed

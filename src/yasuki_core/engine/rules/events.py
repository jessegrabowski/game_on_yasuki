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
    """A card entered a discard pile.

    Attributes
    ----------
    card_id : str
        The card that reached the pile.
    side : Side
        The card's side, one of the two facts a discard-reaction reads ("your action, a Fate card").
    cause : Cause
        Who or what put it there. A ``Rulebook`` cause means no player chose it, so a reaction
        guarded on a seat correctly ignores it.
    from_hand_or_deck : bool
        Whether it was discarded without ever reaching play, which is how cards name the pair of
        hidden zones together: "after this Follower is discarded from your hand or deck". Default
        False, which is what a card discarded out of play or out of a Province reports.
    """

    card_id: str
    side: Side
    cause: Cause
    from_hand_or_deck: bool = False


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
    """A card entered play on the battlefield.

    Attributes
    ----------
    card_id : str
        The card that arrived.
    from_hand : bool
        Whether it came from its owner's hand. An attachment reaches the battlefield from hand by
        Equip and from anywhere else by an effect that attaches it, and cards distinguish the two:
        "after this Follower enters play from your hand". Default False, which is what everything
        arriving from a Province reports.
    """

    card_id: str
    from_hand: bool = False


@dataclass(frozen=True, slots=True)
class Straightened:
    """A bowed card was straightened, whether by the start of its controller's turn or by an effect.
    The event names the change, so a card already standing raises nothing."""

    card_id: str


@dataclass(frozen=True, slots=True)
class Revealed:
    """A face-down card in a Province was turned face-up. A card that arrives already face-up raises
    nothing — the event names the turn, not the resulting state."""

    card_id: str


GameEvent = (
    TurnStarted | CardDiscarded | CounterGained | Destroyed | EnteredPlay | Revealed | Straightened
)

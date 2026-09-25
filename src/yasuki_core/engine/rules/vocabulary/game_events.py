from dataclasses import dataclass

from yasuki_core.engine.players import Cause, PlayerId
from yasuki_core.engine.table import Location, ZoneKey
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
class FavorDiscarded:
    """The Imperial Favor left ``seat``'s control for nobody's.

    The Favor is not a card and carries no cause of its own. A trait reading "after your action
    discards the Favor" reads the seat that announced the action now resolving off the game
    instead.

    Attributes
    ----------
    seat : PlayerId
        The seat that held it.
    """

    seat: PlayerId


@dataclass(frozen=True, slots=True)
class CounterGained:
    """A card gained ``amount`` of a counter: the actual number added, after any floor."""

    card_id: str
    counter: Counter
    amount: int


@dataclass(frozen=True, slots=True)
class Destroyed:
    """A card was destroyed, sent to a discard by destruction, distinct from being discarded from
    hand. ``cause`` names who or what destroyed it, which cards ask about: several react only to a
    Personality destroyed for having zero Chi, and others only to a destruction that was not their
    own doing.

    Attributes
    ----------
    card_id : str
        The card destroyed.
    cause : PlayerId, Rulebook or Trait
        Who or what destroyed it.
    location : Location, optional
        Where the card stood when it was destroyed. It is in its discard by the time this is
        announced, so a card reacting to a destruction "at this location" reads it here. Default
        None, for a destruction announced without one.
    controller : PlayerId, optional
        The seat that controlled it. A created card leaves the table as it is destroyed, so a card
        reacting to "a card you do not control" reads it here. Control is ownership until the
        engine models the two apart. Default None, for a destruction announced without one.
    """

    card_id: str
    cause: Cause
    location: Location | None = None
    controller: PlayerId | None = None


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
class Assigned:
    """A Personality was assigned from home to a battlefield in the Maneuvers Segment, by either
    seat. Raised after the unit has moved, so a trigger reading his location sees the battlefield.

    Attributes
    ----------
    card_id : str
        The Personality assigned.
    battlefield : int
        The battlefield he was sent to.
    seat : PlayerId
        The seat that assigned him.
    """

    card_id: str
    battlefield: int
    seat: PlayerId


@dataclass(frozen=True, slots=True)
class Straightened:
    """A bowed card was straightened, whether by the start of its controller's turn or by an effect.
    The event names the change, so a card already standing raises nothing."""

    card_id: str


@dataclass(frozen=True, slots=True)
class Dishonored:
    """A Personality went from honorable to dishonorable (CR, Honorable and Dishonorable). The event
    names the change, so one already dishonorable raises nothing. ``cause`` names who or what
    dishonored him, which a card reacting only to its own controller's doing reads."""

    card_id: str
    cause: Cause


@dataclass(frozen=True, slots=True)
class Rehonored:
    """A Personality went from dishonorable to honorable. The event names the change, so one already
    honorable raises nothing."""

    card_id: str


@dataclass(frozen=True, slots=True)
class Revealed:
    """A face-down card in a Province was turned face-up. A card that arrives already face-up raises
    nothing. The event names the turn, not the resulting state."""

    card_id: str


@dataclass(frozen=True, slots=True)
class ProducingGold:
    """A card is about to bow and produce Gold, before its yield is read.

    The window a producer's own trait acts in: a grant made here counts toward the production it
    interrupts, which is what "before this Holding bows" and "when this Holding produces" both need.

    Attributes
    ----------
    card_id : str
        The producer about to bow.
    seat : PlayerId
        The seat it produces for.
    """

    card_id: str
    seat: PlayerId


@dataclass(frozen=True, slots=True)
class ProducedGold:
    """A card has bowed and its Gold has reached the pool.

    What a producer owes for a grant it took in the window lands here, since a price payable "after
    it bows" cannot resolve while the yield is still unread.

    Attributes
    ----------
    card_id : str
        The producer that bowed.
    seat : PlayerId
        The seat whose pool the Gold reached.
    amount : int
        The Gold it yielded, after whatever the window granted it.
    """

    card_id: str
    seat: PlayerId
    amount: int


@dataclass(frozen=True, slots=True)
class HonorChanged:
    """A seat's Family Honor moved.

    Raised after the change has landed, so a trigger reading the seat's Honor sees the new value.
    Never raised for a change of zero: an Honor gain of 0 points "is not considered an Honor gain
    for things that check whether a gain happened" (CR, Honor Gains and Losses), and a loss of 0
    likewise.

    Attributes
    ----------
    seat : PlayerId
        The seat whose Honor moved.
    amount : int
        The signed change: positive for a gain, negative for a loss. A trigger that reads "after
        you gain Honor" guards on the sign.
    """

    seat: PlayerId
    amount: int


@dataclass(frozen=True, slots=True)
class ActionResolved:
    """An action has fully resolved, before the Response Step it may open.

    Announced once per action however many decisions or Interrupt steps it passed through, and not
    for a Pass. An action taken inside an Interrupt or Response step is not announced, since the
    action record names the action it answers rather than the step's own.

    Attributes
    ----------
    seat : PlayerId
        The seat that took the action.
    card_id : str or None
        The card the action was taken from, or None for a rulebook action.
    favor : bool
        Whether it was a Favor action (ShE datasheet, The Favor Icon), read as it resolved, which
        is the last moment that is settled.
    printed : bool
        Whether it was a card's printed ability, as against a rulebook action such as a Recruit.
    """

    seat: PlayerId
    card_id: str | None
    favor: bool
    printed: bool


@dataclass(frozen=True, slots=True)
class BattleResolved:
    """A battle has resolved (CR, Resolution), before After Resolution bows and sends home its
    survivors.

    Announced once per battle, after the resolution's destruction and the outcome are recorded and
    before anything bows, so a card that prevents the bow and one reading "after a battle resolves"
    both act here. "After this battle ends" is later, once After Resolution is done, and is the
    ``END_OF_BATTLE`` moment a delayed effect waits for. The outcome fields copy the
    :class:`~yasuki_core.engine.rules.battle.records.BattleOutcome` the attack records, so the
    event outlives the attack that recorded them.

    Attributes
    ----------
    battlefield : int
        The index of the battlefield the battle was fought at.
    province : ZoneKey
        The Province the battlefield sat at, whether or not it still stands.
    attacker : PlayerId
        The seat that declared the attack.
    defender : PlayerId
        The seat whose Province was attacked.
    winner : PlayerId or None
        The seat whose Force was higher, or None if the battle was tied.
    province_destroyed : bool
        Whether the Province was destroyed.
    destroyed : tuple of str
        The ids of the cards the resolution destroyed, in the order they went.
    ever_present : frozenset of (PlayerId, str)
        Each seat and the Personality it ever had at the battlefield during the attack, whether or
        not the Personality was still there when the battle was fought.
    """

    battlefield: int
    province: ZoneKey
    attacker: PlayerId
    defender: PlayerId
    winner: PlayerId | None
    province_destroyed: bool
    destroyed: tuple[str, ...]
    ever_present: frozenset[tuple[PlayerId, str]]


# Events a step fires before it commits anything, to open a window for the cards it concerns. A
# question a trigger asks in one belongs to the step that opened it, so backing out unwinds the
# step's action as it would from any other question of the action's own. Every other event has
# happened by the time a trigger reads it.
WINDOWS: frozenset[type] = frozenset({ProducingGold})

GameEvent = (
    ActionResolved
    | Assigned
    | BattleResolved
    | TurnStarted
    | CardDiscarded
    | CounterGained
    | Destroyed
    | Dishonored
    | EnteredPlay
    | FavorDiscarded
    | HonorChanged
    | ProducedGold
    | ProducingGold
    | Rehonored
    | Revealed
    | Straightened
)

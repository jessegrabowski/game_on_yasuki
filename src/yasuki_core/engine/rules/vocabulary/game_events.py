from dataclasses import dataclass

from yasuki_core.engine.players import Cause, PlayerId
from yasuki_core.engine.rules.turn.structure import Phase
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment, Boundary
from yasuki_core.engine.table import Location, ZoneKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import Counter


@dataclass(frozen=True, slots=True)
class TurnBoundary:
    """``seat``'s turn reached one of its edges, announced at both.

    Attributes
    ----------
    seat : PlayerId
        The seat whose turn it is.
    boundary : Boundary
        Which edge: the beginning, once the seat's cards have straightened and its Provinces are
        revealed, or the end, before the end-of-turn draw and discard, where the CR puts every
        effect "before the turn ends" (CR, Drawing and Discarding Fate Cards).
    """

    seat: PlayerId
    boundary: Boundary


@dataclass(frozen=True, slots=True)
class PhaseStarted:
    """A phase of the active seat's turn has begun, before its first Action Round opens. The Action
    Phase starts after the turn's beginning :class:`~.TurnBoundary`. A card reading "this phase"
    counts the turn's events since the last of these.

    Attributes
    ----------
    phase : Phase
        The phase that began.
    """

    phase: Phase


@dataclass(frozen=True, slots=True)
class BattleSegmentStarted:
    """A segment of the battle being fought has begun, once its Action Round has opened, as "After
    a Combat Segment begins" reads.

    Attributes
    ----------
    segment : BattleSegment
        The segment that began.
    battlefield : int
        The battlefield the battle is fought at.
    """

    segment: BattleSegment
    battlefield: int


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
class ProvinceDestroyed:
    """A Province was destroyed and left the board. Its owner is ``province.owner``."""

    province: ZoneKey


@dataclass(frozen=True, slots=True)
class ProvinceDestroying:
    """A Province is about to be destroyed: announced before the destruction commits, the way
    :class:`~.Destroying` is for a card, so a trait reading "before ... destroys a Province" resolves
    while the Province still stands. Announced only when some card answers it.

    Attributes
    ----------
    province : ZoneKey
        The Province about to be destroyed. Its owner is ``province.owner``.
    seat : PlayerId
        The seat destroying it.
    """

    province: ZoneKey
    seat: PlayerId


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
class CounterChanged:
    """A card's count of a counter moved. Never raised for a change of zero.

    Attributes
    ----------
    card_id : str
        The card whose counter moved.
    counter : Counter
        Which counter.
    amount : int
        The signed change actually made, after the floor at zero: positive for tokens gained,
        negative for tokens removed or destroyed, a card's Sincerity tokens cleared once it is
        Recruited among them. A trigger that reads "after X gains tokens" guards on the sign.
    """

    card_id: str
    counter: Counter
    amount: int


@dataclass(frozen=True, slots=True)
class LastKnownState:
    """A card as it stood before it moved, which is what a reference to it reads once it has gone
    (CR, Created Cards; CR, References to Other Points in Time). Not an event: ``GameState.last_known``
    keeps each card's from when it last left play, and :class:`Destroyed` carries the destroyed
    card's, wherever it stood.

    Attributes
    ----------
    location : Location
        Where the card stood.
    controller : PlayerId
        The seat that controlled it. Control is ownership until the engine models the two apart.
    force : int
        Its Force, every modifier, token and attachment counted.
    """

    location: Location
    controller: PlayerId
    force: int


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
    left_as : LastKnownState
        The card as it stood when it was destroyed, in play or wherever else it was. It is in its
        discard, or off the table if created, by the time this is announced, so a card reacting to a
        destruction "at this location" or of "a card you do not control" reads it here.
    """

    card_id: str
    cause: Cause
    left_as: LastKnownState


@dataclass(frozen=True, slots=True)
class Destroying:
    """A card is about to be destroyed: announced before the destruction commits, once the
    Interrupts taken against it and the negations in force have been read, so a trait reading
    "before this card is destroyed" resolves while the card still stands. The destruction commits
    after the traits it wakes have resolved, and may still be negated by one of them.

    Announced only when some card answers it, so the turn's history holds only the announcements a
    trait answered. A :class:`~.Simultaneously` group's destructions are announced together, as one
    occurrence, before any of them commits. A destruction a state-based rule demands, such as a
    Personality's at zero Chi, is not announced, since no player's action causes it. Unlike a
    window such as :class:`~.ProducingGold`, it is no step announcing itself, so a question a trait
    asks here is the trait's own.

    Attributes
    ----------
    card_id : str
        The card about to be destroyed.
    cause : PlayerId, Rulebook or Trait
        Who or what is destroying it.
    location : Location
        Where the card stands.
    controller : PlayerId
        The seat that controls it.
    leaves_with : str, optional
        The Personality whose unit the card leaves play with (CR, Unit), for a card the destruction
        does not name. A card that stops being in that unit before the destruction commits is not
        destroyed by it. Default None, for the card the destruction names.
    """

    card_id: str
    cause: Cause
    location: Location
    controller: PlayerId
    leaves_with: str | None = None


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
    recruited : bool
        Whether a Recruit brought it into play, which "after the action Recruits X" reads, rather
        than an effect that puts it into play. Default False.
    """

    card_id: str
    from_hand: bool = False
    recruited: bool = False


@dataclass(frozen=True, slots=True)
class Invested:
    """A card was Invested in before its entry into play was paid for, its Gold Cost permanently
    raised by ``amount`` (CR, Invest). What the Invest buys reads this off the action that took it,
    so it is bought once, by the entry it was paid for.

    Attributes
    ----------
    card_id : str
        The card Invested in.
    amount : int
        The Gold Invested. A free Invest is an amount of zero.
    """

    card_id: str
    amount: int


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
class Bowed:
    """An unbowed card was bowed, by an effect, as a cost, by producing Gold, or by a battle's
    resolution. The event names the change, so a card already bowed raises nothing, and neither
    does a card entering play bowed (CR, Bowed and Unbowed)."""

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
class ConditionFulfilled:
    """A condition a card watches has become true (CR, "If" Triggers), as a "Play if" Ring's does.

    Announced once each time the condition turns from false to true while the card is where the
    watch looks, and once when the card arrives there while it already holds, since the arrival is
    a new occurrence. Answered by the card's own watch alone, never by another card, and not a
    thing any action did.

    Attributes
    ----------
    card_id : str
        The card whose condition was fulfilled.
    key : str
        The watch, among the card's others, whose condition it was.
    """

    card_id: str
    key: str


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
        Whether it was a printed action from a card, as against a rulebook action such as a
        Recruit, a trait, or an ability another card grants.
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
    present_at_resolution : frozenset of (PlayerId, str)
        Each seat and the Personality it had at the battlefield as resolution began.
    attacking_force : int
        The attacking army's Force as resolution began, which decided the winner.
    defending_force : int
        The defending army's Force as resolution began.
    destroyed_controllers : frozenset of PlayerId
        The seats whose cards the resolution destroyed. A seat destroys the enemy army's units
        (CR, Battle Resolution), so another seat's here means the seat reading it destroyed cards.
    terrains_played : frozenset of (PlayerId, str)
        Each seat and the Terrain it played at the battlefield from its hand.
    terrains_destroyed : frozenset of (PlayerId, str)
        Each seat and the Terrain at the battlefield it destroyed.
    """

    battlefield: int
    province: ZoneKey
    attacker: PlayerId
    defender: PlayerId
    winner: PlayerId | None
    province_destroyed: bool
    destroyed: tuple[str, ...]
    ever_present: frozenset[tuple[PlayerId, str]]
    present_at_resolution: frozenset[tuple[PlayerId, str]]
    attacking_force: int
    defending_force: int
    destroyed_controllers: frozenset[PlayerId]
    terrains_played: frozenset[tuple[PlayerId, str]]
    terrains_destroyed: frozenset[tuple[PlayerId, str]]


@dataclass(frozen=True, slots=True)
class BattleEnded:
    """A battle has ended, once After Resolution is done (CR, Battle Sequence): the
    ``END_OF_BATTLE`` moment.

    Attributes
    ----------
    resolved : BattleResolved
        How the battle resolved.
    printed_actions : frozenset of PlayerId
        The seats that took a printed action from one of their cards while the battle was being
        fought, the Response Step after its resolution included.
    """

    resolved: BattleResolved
    printed_actions: frozenset[PlayerId]


@dataclass(frozen=True, slots=True)
class DuelDeclared:
    """A duel has been created, announced at each edge of its declaration (CR, Duel).

    Both Personalities and the focusing areas exist by the time this is raised and nothing has been
    focused. At ``Boundary.BEGINNING`` the duel is about to put the first focus-or-strike option, and
    a card acting then changes the duel before it is focused, which is what Hidden Strength reads
    when it compares the two duel stats "at that time". At ``Boundary.END`` that window has closed. A
    trigger that means one of them guards on ``boundary``, as one reading "after you gain Honor"
    guards on the sign of :class:`~.HonorChanged`.

    Attributes
    ----------
    boundary : Boundary
        Which edge of the declaration this is: the window opening, or the duel declared.
    challenger : PlayerId
        The seat whose card created the duel.
    challenged : PlayerId
        The seat challenged, which has the first option.
    challenger_duelist : str
        The id of the challenger's Personality.
    challenged_duelist : str
        The id of the challenged seat's Personality.
    source_card_id : str
        The id of the card that created the duel.
    challenger_stat : int
        The challenger's Personality's duel stat as the duel is declared.
    challenged_stat : int
        The challenged Personality's duel stat as the duel is declared.
    """

    boundary: Boundary
    challenger: PlayerId
    challenged: PlayerId
    challenger_duelist: str
    challenged_duelist: str
    source_card_id: str
    challenger_stat: int
    challenged_stat: int


@dataclass(frozen=True, slots=True)
class CardFocused:
    """A card has been focused, and is in its seat's focusing area face down.

    Attributes
    ----------
    seat : PlayerId
        The seat that focused it.
    card_id : str
        The card focused.
    focused : int
        How many times that seat has now focused in this duel.
    """

    seat: PlayerId
    card_id: str
    focused: int


@dataclass(frozen=True, slots=True)
class StrikeDeclared:
    """A seat has struck, ending the focusing before anything is revealed.

    Attributes
    ----------
    seat : PlayerId
        The seat that struck.
    """

    seat: PlayerId


@dataclass(frozen=True, slots=True)
class FocusedCardsRevealed:
    """Both focus stacks have been turned face up (CR, Duel 0.0.7).

    Attributes
    ----------
    revealed : frozenset of (PlayerId, str)
        Each seat and a card it had focused.
    """

    revealed: frozenset[tuple[PlayerId, str]]


@dataclass(frozen=True, slots=True)
class FocusEffectsResolved:
    """Every revealed Focus Effect has resolved, before the duel is decided (CR, Duel).

    Announced whether or not any card carried one, since the CR's step happens either way.

    Attributes
    ----------
    source_card_id : str
        The id of the card that created the duel.
    """

    source_card_id: str


@dataclass(frozen=True, slots=True)
class DuelResolved:
    """A duel has been decided, before the focused cards are discarded and the duel ends.

    A card asking what the Personalities entered the duel on reads the duel's
    :class:`~.DuelDeclared` out of ``turn_events``, which carries the stats it was declared with.

    Attributes
    ----------
    winners : frozenset of PlayerId
        The seats whose Personalities won, which is empty on a tie. A set rather than one seat
        because the CR lets both Personalities win a duel.
    losers : frozenset of PlayerId
        The seats whose Personalities lost.
    totals : frozenset of (PlayerId, int)
        Each seat and what its Personality totalled.
    source_card_id : str
        The id of the card that created the duel.
    """

    winners: frozenset[PlayerId]
    losers: frozenset[PlayerId]
    totals: frozenset[tuple[PlayerId, int]]
    source_card_id: str


@dataclass(frozen=True, slots=True)
class DuelEnded:
    """A duel is over, whether or not it resolved (CR, Duel). The focused cards have been discarded
    and the focusing areas are gone.

    Attributes
    ----------
    resolved : bool
        Whether the duel reached its resolution. False for a duel a duelist left play in the middle
        of, and for one a refused challenge never started.
    source_card_id : str
        The id of the card that created the duel.
    """

    resolved: bool
    source_card_id: str


# Event types every firing of which is a step announcing itself before it commits. An event that
# names both edges of its own step carries a boundary instead, which opens_a_window reads.
WINDOWS: frozenset[type] = frozenset({ProducingGold})

GameEvent = (
    ActionResolved
    | Assigned
    | BattleResolved
    | BattleEnded
    | BattleSegmentStarted
    | Bowed
    | CardFocused
    | ConditionFulfilled
    | TurnBoundary
    | CardDiscarded
    | CounterChanged
    | ProvinceDestroyed
    | ProvinceDestroying
    | Destroyed
    | Destroying
    | Dishonored
    | DuelDeclared
    | DuelEnded
    | DuelResolved
    | EnteredPlay
    | FocusedCardsRevealed
    | FocusEffectsResolved
    | StrikeDeclared
    | FavorDiscarded
    | HonorChanged
    | Invested
    | PhaseStarted
    | ProducedGold
    | ProducingGold
    | Rehonored
    | Revealed
    | Straightened
)


@dataclass(frozen=True, slots=True)
class NextTime:
    """The next time an event names a card, which a delayed effect waits for as "after Kintaro is
    destroyed" reads (CR, Delayed Effects: "After the next time this game a Samurai assigns to
    attack").

    Attributes
    ----------
    event_type : type
        The kind of event waited for.
    card_id : str
        The card that event names.
    """

    event_type: type
    card_id: str

    def describe(self) -> str:
        return f"after the next {self.event_type.__name__} of {self.card_id}"

    def matches(self, event: GameEvent) -> bool:
        """Whether ``event`` is the occurrence this waits for."""
        return (
            isinstance(event, self.event_type) and getattr(event, "card_id", None) == self.card_id
        )


def opens_a_window(event: GameEvent) -> bool:
    """Whether ``event`` is a step announcing itself before it commits anything, to open a window for
    the cards it concerns.

    A question a trigger asks in a window belongs to the step that opened it, so backing out unwinds
    that step's action as any other question of the action's own would. Every other event has
    happened by the time a trigger reads it.
    """
    if isinstance(event, DuelDeclared):
        return event.boundary is Boundary.BEGINNING
    return type(event) in WINDOWS


def names_both_edges(event_type: type) -> bool:
    """Whether ``event_type`` is announced at each edge of its own step, and so carries a boundary.

    What :func:`~yasuki_core.engine.rules.triggers.on` asks to know whether a registration has to
    name the edge it answers.
    """
    return "boundary" in getattr(event_type, "__annotations__", {})


# What an effect announces before it commits, for the traits that act before it.
Impending = Destroying | ProvinceDestroying

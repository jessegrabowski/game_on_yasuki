from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from collections.abc import Callable
from typing import ClassVar, Self

from yasuki_core.engine import ops
from yasuki_core.engine.registrar import HandlerRegistry
from yasuki_core.engine.rules.battle.presence import place_unit, record_terrain_destroyed
from yasuki_core.engine.rules.board.seats import cards_in_hand
from yasuki_core.engine.rules.rulebook import favor_proxy
from yasuki_core.engine.rules.rulebook.joining import may_join
from yasuki_core.engine.rules.rulebook.recruit_restrictions import may_recruit
from yasuki_core.engine.players import Cause, PlayerId, Trait
from yasuki_core.engine.rules.units.membership import unit_of
from yasuki_core.engine.rules.stats.calculation import effective_stat, stat_changes
from yasuki_core.engine.rules.stats.stat_grants import stat_granters
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import Action
from yasuki_core.engine.rules.vocabulary.decisions import (
    ArrangeCards,
    ChooseAmount,
    ChooseCards,
    ChooseDiscard,
    ChooseDistribution,
    ChooseOption,
    Confirm,
    DecisionRequest,
    PickLimit,
    answerable,
)
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.engine.rules.vocabulary.locations import CardLocation, location_holding
from yasuki_core.engine.rules.vocabulary.looks import Look
from yasuki_core.engine.rules.vocabulary.work import Provenance
from yasuki_core.engine.rules.vocabulary.game_events import (
    Bowed,
    CardDiscarded,
    CounterChanged,
    Destroyed,
    Destroying,
    Impending,
    Dishonored,
    EnteredPlay,
    LastKnownState,
    FavorDiscarded,
    ProvinceDestroyed,
    ProvinceDestroying,
    GameEvent,
    HonorChanged,
    Invested,
    NextTime,
    Rehonored,
    Revealed,
    Straightened,
)
from yasuki_core.engine.rules.vocabulary.modifiers import (
    AbilityGrant,
    Duration,
    CompassionGrant,
    Condition,
    ConditionalModifier,
    DuelStatOverride,
    KeywordGrant,
    Lifetime,
    LobbyModifier,
    Minimum,
    Modifier,
    Negation,
    Ongoing,
    ProvinceModifier,
    SeatAbilityGrant,
    Stat,
    StatChangeNegation,
    StatChanges,
    describe_lifetime,
)
from yasuki_core.engine.rules.state import (
    GameState,
    StraightenDelay,
    claim_once_per_turn,
    seat_game_key,
    seat_once_key,
)
from yasuki_core.engine.rules.turn.structure import (
    AdditionalGrant,
    BEGINNING_OF_ACTION_PHASE,
    END_OF_ACTION_PHASE,
    END_OF_TURN,
    Moment,
    STEP_ROUNDS,
    flow_resolves,
)
from yasuki_core.engine.table import (
    BATTLEFIELD,
    UNPLACED_BOARD_POS,
    DeckKey,
    Location,
    ZoneKey,
    ZoneRole,
    location_of,
    province_keys,
)
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import PersonalityPrint
from yasuki_core.game_pieces.counters import Counter


def pile_for(card: L5RCard, *, banished: bool = False) -> ZoneKey:
    """The pile ``card`` belongs in when it leaves play: its owner's, on the card's own side,
    and its banish rather than its discard when ``banished``.

    Anything not on the Dynasty side is filed with the Fate cards, which is where a Stronghold
    or a Sensei goes for want of a pile of its own. Shared so a Dynasty card cannot reach a Fate
    pile through one path and not another.
    """
    if card.side is Side.DYNASTY:
        role = ZoneRole.DYNASTY_BANISH if banished else ZoneRole.DYNASTY_DISCARD
    else:
        role = ZoneRole.FATE_BANISH if banished else ZoneRole.FATE_DISCARD
    return ZoneKey(card.owner, role)


class Effect(ABC):
    """One change to game state, described as data.

    Triggers and activated abilities return lists of effects rather than mutating the board, and the
    cascade commits each through :meth:`~.perform`.
    """

    __slots__ = ()

    @abstractmethod
    def perform(self, game: GameState) -> list[GameEvent]:
        """Commit this effect and return the events it raises, for the cascade to drain."""

    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        """Whether an ability can pay this effect as a cost. Most effects carry no precondition
        and always can.

        Parameters
        ----------
        bowed_by_cost : frozenset of str, optional
            The cards this same cost bows, which are no longer free to pay the rest of it. Default
            empty.
        """
        return True

    def would_happen(self, game: GameState) -> bool:
        """Whether performing this now would change anything. Most effects always would. A bow of a
        card already bowed would not, since a card bows only in going from unbowed to bowed (CR,
        Bowed and Unbowed), so "its next bowing" is still to come after one."""
        return True

    @property
    def subject_id(self) -> str | None:
        """The card this effect acts on, which a negation naming a card matches, or None for an
        effect that acts on no card. Card memory, such as a once-per-turn record, acts on none."""
        return None

    def is_negatable(self, game: GameState) -> bool:
        """Whether a negation in force can reach this effect as it commits. True unless the effect
        is no effect at all, such as an action's targeting."""
        return True

    @abstractmethod
    def describe(self) -> str:
        """One short line naming what this effect does, for a cascade trace. Abstract so a new
        effect cannot ship unreadable: the generated ``repr`` inlines whole nested dataclasses."""

    def narrate(self, game: GameState) -> str:
        """The effect as the seat offered an Interrupt against it reads it: cards and players by
        name, unlike :meth:`~.Effect.describe`, which names them by id for the log."""
        return self.describe()

    def is_interruptible(self, game: GameState) -> bool:
        """Whether the Interrupt step is open against this effect at all, when it is an action's
        own. True unless the effect is nothing to interrupt, such as an Honor change of zero or a
        loss a card prevents."""
        return True

    def follow_on(self, game: GameState) -> tuple["Effect", ...]:
        """The effects this one produces once performed, which the cascade applies next, each
        through its own Interrupt step. Read after :meth:`~.Effect.perform`, on the board it left.
        Empty for an effect that is complete in itself."""
        return ()

    def impending(self, game: GameState) -> tuple[Impending, ...]:
        """What is announced before this effect commits, for the traits that act before it: read on
        the board as it stands, before :meth:`~.Effect.perform`. Empty for an effect nothing acts
        before."""
        return ()


class InterruptingEffect(Effect, ABC):
    """An effect that pauses the cascade to put a question to a seat.

    The walker records :meth:`request` as the pending decision and stashes the rest of the cascade,
    resuming once the seat answers. It calls :meth:`~.perform` only on one whose :meth:`pauses`
    says there is no one to ask.
    """

    __slots__ = ()

    @abstractmethod
    def request(self, game: GameState) -> DecisionRequest | None:
        """The decision to put to the seat, or None when the work it queued needs no answer, which
        then runs as the stack drains, ahead of the rest of the cascade."""

    def is_interruptible(self, game: GameState) -> bool:
        """False: a question the action asks is nothing to interrupt, and what its answer produces
        is not known until it is answered, so neither is offered at the Interrupt step."""
        return False

    def pauses(self, game: GameState) -> bool:
        """Whether the cascade stops here. True unless a subclass finds nobody to answer, in which
        case the walker performs the effect instead of asking."""
        return True

    def possible_answers(self) -> tuple[Effect, ...]:
        """Each effect the answer may make of this one, which the Interrupt step reads as the
        action's text (CR, Blind Cards Rule). An Interrupt bound to one applies only if the answer
        makes it, since its effect waits for that effect to occur (CR, Interrupt Actions). None
        unless a subclass answers in place."""
        return ()

    @property
    def answers_in_place(self) -> bool:
        """Whether the answer makes this effect into one of :meth:`possible_answers`, which takes
        its place where it stood, the first of a :class:`To` included."""
        return bool(self.possible_answers())

    def answered(self, choices: tuple[str, ...]) -> Effect:
        """The effect the seat's ``choices`` make of this one, for one that answers in place. Raise
        ``RuntimeError`` for one that does not."""
        raise RuntimeError(f"{type(self).__name__} is not answered in place")

    def is_negatable(self, game: GameState) -> bool:
        """False: a question is no effect, and what its answer produces is checked as it commits.
        An effect that asks before it happens, as a chosen discard does, says True."""
        return False

    def perform(self, game: GameState) -> list[GameEvent]:
        """Never reached: the walker records :meth:`~.InterruptingEffect.request` and pauses instead
        of committing."""
        raise RuntimeError(
            f"{type(self).__name__} pauses the cascade; it is never applied directly"
        )


@dataclass(frozen=True, slots=True)
class Negated(Effect):
    """An effect an Interrupt negated: it resolves as nothing where ``effect`` would have.

    What an Interrupt returns as its :class:`~yasuki_core.engine.rules.abilities.model.Interruption`
    replacement when the card reads "negate". Keeping the negated effect lets the trace and the
    Interrupt step name what was negated.

    Attributes
    ----------
    effect : Effect
        The effect that would have resolved.
    """

    effect: Effect

    def perform(self, game: GameState) -> list[GameEvent]:
        return []

    def is_negatable(self, game: GameState) -> bool:
        """False: it is already nothing, so a negation has nothing left to stop."""
        return False

    def describe(self) -> str:
        return f"negated: {self.effect.describe()}"

    def narrate(self, game: GameState) -> str:
        return f"negated: {self.effect.narrate(game)}"


@dataclass(frozen=True, slots=True)
class GrantNegation(Effect):
    """Record a continuous negation: the effects ``negation`` matches are negated while it lasts.

    Attributes
    ----------
    negation : Negation
        The record, naming its source, what it negates and how long it lasts.
    """

    negation: Negation

    def describe(self) -> str:
        lifetime = describe_lifetime(self.negation.duration)
        return f"{self.negation.source_id} negates effects ({lifetime})"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.ongoing.append(self.negation)
        return []


@dataclass(frozen=True, slots=True)
class NegateAction(Effect):
    """Negate the action held at the Interrupt step: every effect it has yet to hand over is
    negated, whatever produces it, and its targeting is not (CR, Negate an Action).

    Attributes
    ----------
    source_id : str
        The card negating the action.
    """

    source_id: str

    def describe(self) -> str:
        return f"{self.source_id} negates the action"

    def perform(self, game: GameState) -> list[GameEvent]:
        """Raise ``RuntimeError`` if no action is held at the Interrupt step."""
        # Imported where it is used: the cascade imports this module for the effects it applies.
        from yasuki_core.engine.rules.triggers import HeldAction

        negation = Negation(self.source_id, Duration.UNTIL_END_OF_TURN, effect_kind=Effect)
        for index in reversed(range(len(game.stack))):
            held = game.stack[index]
            if isinstance(held, HeldAction):
                negations = (*held.provenance.negations, negation)
                provenance = replace(held.provenance, negations=negations)
                game.stack[index] = replace(held, provenance=provenance)
                return []
        raise RuntimeError("no action is held at the Interrupt step to negate")


@dataclass(frozen=True, slots=True)
class GrantCompassion(Effect):
    """Record ``grant``, treating its seat as having Compassion while it lasts."""

    grant: CompassionGrant

    def describe(self) -> str:
        covered = "" if self.grant.card_id is None else f" for {self.grant.card_id}"
        lifetime = describe_lifetime(self.grant.duration)
        return (
            f"{self.grant.source_id} gives {self.grant.seat.name} Compassion{covered} ({lifetime})"
        )

    def perform(self, game: GameState) -> list[GameEvent]:
        game.ongoing.append(self.grant)
        return []


@dataclass(frozen=True, slots=True)
class AdjustCounter(Effect):
    """Add ``delta`` to a counter on a card (floored at zero by the card). A grant is a positive
    delta, a removal negative. The rules-side twin of the sandbox ``AdjustCounter`` intent, applied
    through :meth:`Effect.perform` rather than ``apply_intent``."""

    card_id: str
    counter: Counter
    delta: int

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        return f"{self.delta:+d} {self.counter.name} on {self.card_id}"

    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        """A removal needs the card to hold enough of the counter. A grant always applies."""
        if self.delta >= 0:
            return True
        card = game.table.cards_by_id.get(self.card_id)
        return card is not None and card.counters.get(self.counter.key, 0) >= -self.delta

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None:
            return []
        before = card.counters.get(self.counter.key, 0)
        card.adjust_counter(self.counter.key, self.delta)
        changed = card.counters.get(self.counter.key, 0) - before
        if changed == 0:
            return []
        return [CounterChanged(self.card_id, self.counter, changed)]


@dataclass(frozen=True, slots=True)
class DrawCard(Effect):
    """``seat`` draws a card from its fate deck."""

    seat: PlayerId

    def describe(self) -> str:
        return f"{self.seat.name} draws a card"

    def perform(self, game: GameState) -> list[GameEvent]:
        ops.draw_to_hand(game.table, self.seat)
        return []


@dataclass(frozen=True, slots=True)
class Move(Effect):
    """Put ``card_id``'s whole unit at ``to`` (CR, Unit). A unit already there stays where it is.

    Attributes
    ----------
    card_id : str
        Any card in the unit being moved.
    to : Location
        Where the unit ends up: a seat's home, or a battlefield.
    """

    card_id: str
    to: Location

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        where = (
            f"{self.to.seat.name}'s home"
            if self.to.is_home
            else f"battlefield {self.to.battlefield}"
        )
        return f"move {self.card_id} to {where}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is not None:
            place_unit(game, card, self.to)
        return []


@dataclass(frozen=True, slots=True)
class Show(Effect):
    """Reveal ``card_id`` to the other seats. Narrower than turning it face up: its owner is telling
    the table what it is, and they go on knowing once it is hidden again."""

    card_id: str

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        return f"show {self.card_id}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is not None:
            card.show()
        return []


@dataclass(frozen=True, slots=True)
class MoveToHand(Effect):
    """Put ``card_id`` into ``seat``'s hand from wherever it is. A card that no longer exists is a
    no-op."""

    card_id: str
    seat: PlayerId

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        return f"{self.card_id} to {self.seat.name}'s hand"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is not None:
            _move_card(game, card, ZoneKey(self.seat, ZoneRole.HAND))
        return []


def _as_it_stands(game: GameState, card: L5RCard, *, destroyed: bool = False) -> LastKnownState:
    return LastKnownState(
        location_of(game.table, card),
        card.owner,
        effective_stat(game, card, Stat.FORCE),
        effective_stat(game, card, Stat.CHI),
        destroyed=destroyed,
    )


def _named(game: GameState, card_id: str) -> str:
    """``card_id``'s card by name, or its id once a created card has left the table (CR, Create)."""
    card = game.table.cards_by_id.get(card_id)
    return card_id if card is None else card.name


def _in_play(game: GameState, card: L5RCard) -> bool:
    return any(held is card for held in game.table.battlefield.cards)


def _move_card(
    game: GameState, card: L5RCard, dest: ZoneKey | DeckKey, **placement: object
) -> None:
    """Move ``card`` as an effect does, remembering it as it stood if it is leaving play, which is
    what a later reference to it reads (CR, References to Other Points in Time). Every effect that
    can take a card out of play moves it through here or through :func:`_remove_unit`, so a card
    moving between places out of play keeps the record of when it last stood in play, and one
    removed from the game on leaving play is removed whatever sent it."""
    if _in_play(game, card):
        game.last_known[card.id] = _as_it_stands(game, card)
        dest = _leaving_play_to(game, card, dest)
    ops.move_card(game.table, card, dest, **placement)


def _leaving_play_to(game: GameState, card: L5RCard, dest: ZoneKey | DeckKey) -> ZoneKey | DeckKey:
    """Where ``card``, leaving play for ``dest``, goes: its banish pile when it is to be removed
    from the game on leaving play, which spends that record, and ``dest`` otherwise."""
    if card.id not in game.banished_on_leaving_play:
        return dest
    game.banished_on_leaving_play -= {card.id}
    return pile_for(card, banished=True)


def _remove_unit(
    game: GameState, card: L5RCard, *, banished: bool = False, destroyed: bool = False
) -> tuple[tuple[L5RCard, LastKnownState], ...]:
    """Send ``card`` and everything attached to him out of play, to their discards or to their
    banishes when ``banished``. Return each member of the unit that left with how it stood, read
    for the whole unit before any of it moved so each member's Force still counts the others, so
    the caller can announce each departure in its own words (CR, Unit).

    A created card among them has no pile of either kind and is taken off the table instead, which
    the move itself sees to (CR, Create). It still announces its departure, because a card reacting
    to a Follower being destroyed does not care where the Follower came from.

    Each record says the departure was a destruction when ``destroyed``, which is what tells a
    card lying in a pile from one discarded there without dying.
    """
    in_play = _in_play(game, card)
    stood = tuple(
        (member, _as_it_stands(game, member, destroyed=destroyed)) for member in unit_of(game, card)
    )
    for member, state in stood:
        dest = pile_for(member, banished=banished)
        if in_play:
            game.last_known[member.id] = state
            dest = _leaving_play_to(game, member, dest)
        ops.move_card(game.table, member, dest)
    return stood


def _leaves_for_pile(game: GameState, card_id: str, *, banished: bool) -> bool:
    """Whether the card goes to its pile: it is on the table, not in that pile already, and not
    banished, since a banished card is out of the game."""
    card = game.table.cards_by_id.get(card_id)
    if card is None:
        return False
    piles = game.table.zones
    return card not in piles[pile_for(card, banished=banished)].cards and (
        banished or card not in piles[pile_for(card, banished=True)].cards
    )


def _destroying_seat(game: GameState, cause: Cause) -> PlayerId | None:
    """The seat a destruction belongs to: the seat that acted, or the controller of the card whose
    trait did it. None for the rulebook, and for a trait whose card has left the table."""
    if isinstance(cause, PlayerId):
        return cause
    if isinstance(cause, Trait):
        source = game.table.cards_by_id.get(cause.card_id)
        return None if source is None else source.owner
    return None


@dataclass(frozen=True, slots=True)
class Destroy(Effect):
    """Destroy a card, sending it to its owner's discard by side. A Personality takes his unit with
    him: everything attached leaves play the same way he does (CR, Unit), each announcing its own
    destruction and naming the same cause.

    Attributes
    ----------
    card_id : str
        The card to destroy.
    cause : PlayerId, Rulebook or Trait
        Who or what destroyed it: the seat whose card did, or the rule that demanded it.
    negatable : bool, optional
        Whether a negation can stop it. False for a destruction the rules say cannot be negated,
        as seppuku's. Default True.
    """

    card_id: str
    cause: Cause
    negatable: bool = True

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        return f"destroy {self.card_id}"

    def is_negatable(self, game: GameState) -> bool:
        return self.negatable

    def impending(self, game: GameState) -> tuple[Destroying, ...]:
        """One :class:`~.Destroying` for each card of the unit about to leave play, or none for a
        card not in play."""
        card = game.table.cards_by_id.get(self.card_id)
        if card is None or not any(held is card for held in game.table.battlefield.cards):
            return ()
        location = location_of(game.table, card)
        return tuple(
            Destroying(
                member.id,
                self.cause,
                location,
                member.owner,
                leaves_with=None if member is card else card.id,
            )
            for member in unit_of(game, card)
        )

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None:
            return []
        location = location_of(game.table, card)
        destroyer = _destroying_seat(game, self.cause)
        if (
            destroyer is not None
            and location.battlefield is not None
            and keywords.TERRAIN in effective_keywords(game, card)
        ):
            record_terrain_destroyed(game, destroyer, card, battlefield=location.battlefield)
        return [
            Destroyed(member.id, self.cause, stood)
            for member, stood in _remove_unit(game, card, destroyed=True)
        ]


@dataclass(frozen=True, slots=True)
class Discard(Effect):
    """Put a card in its owner's discard pile by side, announcing the discard.

    Attributes
    ----------
    card_id : str
        The card to discard.
    cause : PlayerId, Rulebook or Trait
        Who or what discarded it: the seat whose action did (which a discard reaction reads to
        tell its own doing from its opponent's), or the rule that demanded it.
    """

    card_id: str
    cause: Cause

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        return f"{self.cause.name} discards {self.card_id}"

    def would_happen(self, game: GameState) -> bool:
        """False for a card already gone, already in its discard pile or banished, which nothing
        moves."""
        return _leaves_for_pile(game, self.card_id, banished=False)

    def perform(self, game: GameState) -> list[GameEvent]:
        if not self.would_happen(game):
            return []
        card = game.table.cards_by_id[self.card_id]
        left = location_holding(game.table, card)
        removed = _remove_unit(game, card)
        return [CardDiscarded(member.id, member.side, self.cause, left) for member, _ in removed]


@dataclass(frozen=True, slots=True)
class Banish(Effect):
    """Take a card out of the game, to its owner's banish pile by side.

    Banishing is not a destruction and not a discard: nothing reacts to it and the card is out of
    reach of anything that recurs from a discard pile. A Personality takes his unit with him, as he
    does however he leaves (CR, Unit). A created card leaves the table entirely. Banishing one and
    destroying one come to the same thing, since neither pile can hold it.

    Attributes
    ----------
    card_id : str
        The card to banish. A card already gone is a no-op, which is what a delayed banish finds
        when something else got there first.
    """

    card_id: str

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        return f"banish {self.card_id}"

    def would_happen(self, game: GameState) -> bool:
        """False for a card already gone or already banished, which nothing moves."""
        return _leaves_for_pile(game, self.card_id, banished=True)

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None:
            return []
        _remove_unit(game, card, banished=True)
        return []


@dataclass(frozen=True, slots=True)
class DelayedEffect(Effect):
    """Hold ``effect`` until ``until``, then resolve it: the CR's delayed effect.

    Nothing is decided at the moment it resolves: a held effect whose card has since left the table
    is a no-op, so a delay never has to be withdrawn.

    Attributes
    ----------
    effect : Effect
        What resolves later.
    until : Moment or NextTime
        The boundary of play it waits for, or the next time an event names a card. Resolving a
        delay to a moment the flow never reaches raises ``ValueError`` rather than holding the
        effect for the rest of the game.
    """

    effect: Effect
    until: Moment | NextTime

    def describe(self) -> str:
        return f"{self.effect.describe()} {self.until.describe()}"

    def perform(self, game: GameState) -> list[GameEvent]:
        if isinstance(self.until, Moment) and not flow_resolves(self.until):
            raise ValueError(f"nothing resolves {self.until.describe()}")
        game.delayed.append((self.until, self.effect))
        return []


@dataclass(frozen=True, slots=True)
class Attributed(Effect):
    """``effect``, resolving as the effect of whatever ``provenance`` names instead of as one of
    the effects around it, with those effects stashed so their order holds.

    A delayed effect stays the effect of the action that scheduled it, so a negation of the
    action's effects in force when it resolves still reaches it (CR, Delayed Effects). A card's own
    effects before it enters play are its trait's even among the Recruit's, so the Interrupt step
    does not offer them (CR, Traits).

    Attributes
    ----------
    effect : Effect
        What resolves.
    provenance : Provenance
        Whose effect it is: the scheduling action's acting card and the negations it spent, or no
        action's at all.
    """

    effect: Effect
    provenance: Provenance

    def describe(self) -> str:
        return self.effect.describe()

    def narrate(self, game: GameState) -> str:
        return self.effect.narrate(game)

    def is_interruptible(self, game: GameState) -> bool:
        """False: whether ``effect`` is open to the Interrupt step is ``provenance``'s to say."""
        return False

    def is_negatable(self, game: GameState) -> bool:
        """False: ``effect`` is checked when it resolves under ``provenance``."""
        return False

    def perform(self, game: GameState) -> list[GameEvent]:
        """Never reached: the cascade resolves ``effect`` under ``provenance`` instead."""
        raise RuntimeError("an attributed effect is resolved by the cascade")


@dataclass(frozen=True, slots=True)
class Evaluate(Effect):
    """Produce the effects the resolver named ``resolver`` returns for the board as it stands when
    this resolves.

    What a card holds in a :class:`~.DelayedEffect` when what it does at the later moment depends
    on how that moment went: "after this battle's resolution, if the Province was not destroyed,
    gain 2 Honor" reads the outcome only once there is one. The resolver is a registered choice
    resolver, called with ``subjects`` as its chosen ids.

    Attributes
    ----------
    resolver : str
        The registered choice resolver that decides the effects.
    source_id : str
        The card the effect belongs to, handed to the resolver.
    seat : PlayerId
        The seat the effect belongs to, handed to the resolver.
    subjects : tuple of str, optional
        The ids the resolver reads as its chosen cards. Default empty.
    """

    resolver: str
    source_id: str
    seat: PlayerId
    subjects: tuple[str, ...] = ()

    def describe(self) -> str:
        return f"{self.source_id} evaluates {self.resolver}"

    def perform(self, game: GameState) -> list[GameEvent]:
        return []

    def follow_on(self, game: GameState) -> tuple[Effect, ...]:
        from yasuki_core.engine.rules.triggers import CHOICE_RESOLVERS

        return tuple(
            CHOICE_RESOLVERS[self.resolver](game, self.source_id, self.subjects, self.seat)
        )


@dataclass(frozen=True, slots=True)
class DestroyProvince(Effect):
    """Destroy the Province ``zone``: its contents go face-up to its owner's discard pile and the
    Province itself leaves the board. A Province already gone is a no-op.

    Attributes
    ----------
    seat : PlayerId
        The seat destroying it, whose discard takes any card with no pile of its own.
    zone : ZoneKey
        The Province to destroy.
    """

    seat: PlayerId
    zone: ZoneKey

    def describe(self) -> str:
        return f"destroy {self.seat.name}'s province {self.zone.idx}"

    def impending(self, game: GameState) -> tuple[ProvinceDestroying, ...]:
        """A :class:`~.ProvinceDestroying` for a Province still on the board, or none for one already
        gone."""
        if self.zone not in game.table.zones:
            return ()
        return (ProvinceDestroying(self.zone, self.seat),)

    def perform(self, game: GameState) -> list[GameEvent]:
        if self.zone not in game.table.zones:
            return []
        # Its cards reach the discard pile without being discarded (CR, Provinces), so only the
        # Province's destruction is announced.
        ops.destroy_province(game.table, self.seat, self.zone)
        return [ProvinceDestroyed(self.zone)]


@dataclass(frozen=True, slots=True)
class GainProvince(Effect):
    """``seat`` gains a Province, created to the left of its leftmost and then refilled (ShE
    datasheet). It takes a fresh id, so no record naming another Province changes meaning.

    Attributes
    ----------
    seat : PlayerId
        The seat gaining the Province.
    """

    seat: PlayerId

    def describe(self) -> str:
        return f"{self.seat.name} gains a province"

    def perform(self, game: GameState) -> list[GameEvent]:
        ops.gain_province(game.table, self.seat)
        return []

    def follow_on(self, game: GameState) -> tuple[Effect, ...]:
        """Refill the gained Province, which is now the leftmost."""
        return (RefillProvince(province_keys(game.table, self.seat)[0]),)


@dataclass(frozen=True, slots=True)
class PlaceInProvince(Effect):
    """Put a card into a Province face-up. A no-op when the card is gone or the Province is full."""

    card_id: str
    zone: ZoneKey

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        return f"place {self.card_id} in {self.zone.owner.name} province {self.zone.idx}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        province = game.table.zones.get(self.zone)
        if card is None or province is None or not province.has_capacity():
            return []
        _move_card(game, card, self.zone)
        card.turn_face_up()
        return []


@dataclass(frozen=True, slots=True)
class ShuffleDeck(Effect):
    """Shuffle a deck, drawing from the game's own stream so a replay shuffles the same way."""

    deck: DeckKey

    def describe(self) -> str:
        return f"shuffle {self.deck.owner.name}'s {self.deck.side.name.lower()} deck"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.table.decks[self.deck].shuffle(game.rng)
        return []


@dataclass(frozen=True, slots=True)
class TakeFavor(Effect):
    """Give ``seat`` the Imperial Favor.

    One player controls the Favor at a time and changes of control are instantaneous (Twenty
    Festivals CR, The Imperial Favor), so whoever held it loses it in this same step.
    """

    seat: PlayerId

    def describe(self) -> str:
        return f"{self.seat.name} takes the Imperial Favor"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.favor_holder = self.seat
        favor_proxy.sync_proxy(game)
        return []


@dataclass(frozen=True, slots=True)
class DiscardFavor(Effect):
    """Return the Imperial Favor to uncontrolled, if ``seat`` is the one holding it.

    Discarding it leaves it held by nobody rather than passing it on (Twenty Festivals CR, The
    Imperial Favor).
    """

    seat: PlayerId

    def describe(self) -> str:
        return f"{self.seat.name} discards the Imperial Favor"

    def perform(self, game: GameState) -> list[GameEvent]:
        if game.favor_holder is not self.seat:
            return []
        game.favor_holder = None
        favor_proxy.sync_proxy(game)
        return [FavorDiscarded(self.seat)]


def _next_record(game: GameState) -> int:
    """Number the stat modifier about to be recorded."""
    game.records_made += 1
    return game.records_made


@dataclass(frozen=True, slots=True)
class GrantModifier(Effect):
    """Record a continuous stat modifier: the ``source`` card grants ``target`` a change of
    ``amount`` to ``stat`` for ``duration``. The single created-effect entry point. A card's
    counters and attachments grant their bonuses without one (they are derived on read)."""

    source_id: str
    target_id: str
    stat: Stat
    amount: int
    duration: Lifetime

    @property
    def subject_id(self) -> str:
        return self.target_id

    def describe(self) -> str:
        return (
            f"{self.source_id} grants {self.target_id} {self.amount:+d} "
            f"{self.stat.name} ({describe_lifetime(self.duration)})"
        )

    def perform(self, game: GameState) -> list[GameEvent]:
        game.ongoing.append(
            Modifier(
                self.source_id,
                self.target_id,
                self.stat,
                self.amount,
                self.duration,
                serial=_next_record(game),
            )
        )
        return []


@dataclass(frozen=True, slots=True)
class GrantStatChangeNegation(Effect):
    """Negate the bonuses, penalties or both to ``stat`` on ``subjects`` for ``duration`` (CR,
    Prevention), recording which changes stand on them as it commits so only those are negated,
    unless ``reaches_new`` negates new ones too.

    Attributes
    ----------
    source_id : str
        The card the negation comes from.
    subjects : frozenset of str
        The cards whose changes it negates.
    stat : Stat
        The stat whose changes it negates.
    changes : ~yasuki_core.engine.rules.vocabulary.modifiers.StatChanges
        Which changes it negates.
    duration : ~yasuki_core.engine.rules.vocabulary.modifiers.Duration or Moment
        When it stops applying.
    reaches_new : bool, optional
        Whether changes arriving after it are negated too, as "current and new" reads. Default
        False.
    """

    source_id: str
    subjects: frozenset[str]
    stat: Stat
    changes: StatChanges
    duration: Lifetime
    reaches_new: bool = False

    def describe(self) -> str:
        reached = ", ".join(sorted(self.subjects))
        return (
            f"{self.source_id} negates {self.changes.value} to {self.stat.name} on {reached} "
            f"({describe_lifetime(self.duration)})"
        )

    def perform(self, game: GameState) -> list[GameEvent]:
        by_id = game.table.cards_by_id
        granters = stat_granters(game)
        current = frozenset(
            identity
            for subject in self.subjects
            if subject in by_id
            for identity in stat_changes(game, by_id[subject], self.stat, granters=granters)
        )
        negation = StatChangeNegation(
            self.source_id,
            self.subjects,
            self.stat,
            self.changes,
            self.duration,
            current=current,
            reaches_new=self.reaches_new,
        )
        game.ongoing.append(negation)
        return []


@dataclass(frozen=True, slots=True)
class Invest(Effect):
    """Invest ``amount`` in ``card_id`` before its entry into play is paid for: permanently raise
    its Gold Cost by that much, and announce the Invest for what it buys once the card has entered
    play (CR, Invest).

    Attributes
    ----------
    card_id : str
        The card Invested in.
    amount : int
        The Gold Invested. A free Invest is an amount of zero, and is still an Invest.
    """

    card_id: str
    amount: int

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        return f"invest {self.amount} in {self.card_id}"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.ongoing.append(
            Modifier(
                self.card_id,
                self.card_id,
                Stat.GOLD_COST,
                self.amount,
                Duration.PERMANENT,
                serial=_next_record(game),
            )
        )
        return [Invested(self.card_id, self.amount)]


@dataclass(frozen=True, slots=True)
class GrantConditionalModifier(Effect):
    """Record a continuous stat modifier on every card meeting ``condition``: the ``source`` card
    grants a change of ``amount`` to ``stat`` for ``duration`` to whichever cards satisfy it at
    each read. The conditional counterpart of :class:`~.GrantModifier`."""

    source_id: str
    condition: Condition
    stat: Stat
    amount: int
    duration: Lifetime

    def describe(self) -> str:
        return (
            f"{self.source_id} grants {self.amount:+d} {self.stat.name} while "
            f"{self.condition.value} ({describe_lifetime(self.duration)})"
        )

    def perform(self, game: GameState) -> list[GameEvent]:
        game.ongoing.append(
            ConditionalModifier(
                self.source_id,
                self.condition,
                self.stat,
                self.amount,
                self.duration,
                serial=_next_record(game),
            )
        )
        return []


@dataclass(frozen=True, slots=True)
class GrantAbility(Effect):
    """Record a continuous ability grant: the ``source`` card gives ``target`` the ability its
    registered factory builds from ``context``, for ``duration``. The ability counterpart of
    :class:`~.GrantModifier`."""

    source_id: str
    target_id: str
    context: tuple[str, ...]
    duration: Lifetime

    @property
    def subject_id(self) -> str:
        return self.target_id

    def describe(self) -> str:
        lifetime = describe_lifetime(self.duration)
        return f"{self.source_id} grants {self.target_id} an ability ({lifetime})"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.ongoing.append(
            AbilityGrant(self.source_id, self.target_id, self.context, self.duration)
        )
        return []


@dataclass(frozen=True, slots=True)
class GrantSeatAbility(Effect):
    """Record a continuous ability grant on a player: the ``source`` card gives every card ``seat``
    owns the ability its registered factory builds from ``context``, for ``duration``. The
    player-scoped counterpart of :class:`~.GrantAbility`."""

    source_id: str
    seat: PlayerId
    context: tuple[str, ...]
    duration: Lifetime

    def describe(self) -> str:
        lifetime = describe_lifetime(self.duration)
        return f"{self.source_id} grants {self.seat.name}'s cards an ability ({lifetime})"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.ongoing.append(
            SeatAbilityGrant(self.source_id, self.seat, self.context, self.duration)
        )
        return []


@dataclass(frozen=True, slots=True)
class RevokeGrants(Effect):
    """Remove every ability grant the ``source`` card gave, whatever its duration: a grant good
    for one use is revoked by the use."""

    source_id: str

    def describe(self) -> str:
        return f"{self.source_id} revokes its grants"

    def is_interruptible(self, game: GameState) -> bool:
        """False: bookkeeping on a record, with nothing on the board to interrupt."""
        return False

    def perform(self, game: GameState) -> list[GameEvent]:
        game.ongoing = [
            recorded
            for recorded in game.ongoing
            if recorded.source_id != self.source_id
            or not isinstance(recorded, AbilityGrant | SeatAbilityGrant)
        ]
        return []


@dataclass(frozen=True, slots=True)
class GrantMinimum(Effect):
    """Record a continuous stat minimum: the ``source`` card floors ``target``'s ``stat`` at
    ``value`` for ``duration`` (CR, Minimums and Maximums).

    The minimum counterpart of :class:`~.GrantModifier`. For "to a minimum of N" wording, use
    :class:`~.GrantModifier` with a capped amount instead.
    """

    source_id: str
    target_id: str
    stat: Stat
    value: int
    duration: Lifetime

    @property
    def subject_id(self) -> str:
        return self.target_id

    def describe(self) -> str:
        return (
            f"{self.source_id} gives {self.target_id} a minimum {self.stat.name} of {self.value} "
            f"({describe_lifetime(self.duration)})"
        )

    def perform(self, game: GameState) -> list[GameEvent]:
        game.ongoing.append(
            Minimum(self.source_id, self.target_id, self.stat, self.value, self.duration)
        )
        return []


@dataclass(frozen=True, slots=True)
class GrantDuelStat(Effect):
    """Record which stat ``target``'s duels compare for ``duration`` (CR, Duel Stat).

    The stat is named per Personality, so one duelist can compare Force while the other compares
    Chi.
    """

    source_id: str
    target_id: str
    stat: Stat
    duration: Lifetime

    @property
    def subject_id(self) -> str:
        return self.target_id

    def describe(self) -> str:
        return (
            f"{self.source_id} gives {self.target_id} a duel stat of {self.stat.name} "
            f"({describe_lifetime(self.duration)})"
        )

    def perform(self, game: GameState) -> list[GameEvent]:
        game.ongoing.append(
            DuelStatOverride(self.source_id, self.target_id, self.stat, self.duration)
        )
        return []


@dataclass(frozen=True, slots=True)
class GrantProvinceStrength(Effect):
    """Record a continuous Province Strength modifier: the ``source`` card adjusts ``province`` by
    ``amount`` for ``duration``.

    The Province counterpart of :class:`~.GrantModifier`, targeting a province slot instead of a
    Personality.
    """

    source_id: str
    province: ZoneKey
    amount: int
    duration: Lifetime

    def describe(self) -> str:
        return (
            f"{self.source_id} gives {self.province.token} {self.amount:+d} province strength "
            f"({describe_lifetime(self.duration)})"
        )

    def perform(self, game: GameState) -> list[GameEvent]:
        game.ongoing.append(
            ProvinceModifier(self.source_id, self.province, self.amount, self.duration)
        )
        return []


@dataclass(frozen=True, slots=True)
class SpendOncePerTurn(Effect):
    """Claim ``card_id``'s once-per-turn use of ``tag``.

    What a card charges when its limit is the whole price: an offer that costs nothing but may
    only be taken once a turn. Spent when the price is paid rather than when it is offered, since
    a cost is read to judge legality as well as to charge it.
    """

    card_id: str
    tag: str

    def describe(self) -> str:
        return f"{self.card_id} spends its {self.tag} for the turn"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is not None:
            claim_once_per_turn(game, card, self.tag)
        return []


@dataclass(frozen=True, slots=True)
class SpendSeatOncePerTurn(Effect):
    """Claim ``seat``'s once-per-turn use of ``tag``: the :class:`~.SpendOncePerTurn` of a limit
    that rests on the player rather than on a card."""

    seat: PlayerId
    tag: str

    def describe(self) -> str:
        return f"{self.seat.name} spends {self.tag} for the turn"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.use_once(seat_once_key(self.seat, self.tag, game.turn))
        return []


@dataclass(frozen=True, slots=True)
class SpendSeatOncePerGame(Effect):
    """Claim ``seat``'s once-per-game use of ``tag``: the :class:`~.SpendSeatOncePerTurn` of a limit
    that never resets. :func:`~.seat_used_this_game` reads it."""

    seat: PlayerId
    tag: str

    def describe(self) -> str:
        return f"{self.seat.name} spends {self.tag} for the game"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.use_once(seat_game_key(self.seat, self.tag))
        return []


@dataclass(frozen=True, slots=True)
class PayFavorCost(Effect):
    """Record that the action now resolving is paying a Favor cost.

    Carried by the cost itself rather than set when the action is announced, so an action offering
    the Favor as one of two ways to pay counts as a Favor action only on the branch that takes it
    (ShE datasheet, The Favor Icon). An Interrupt or a Response paying one records nothing, because
    the action record describes the action they answer, and a Favor payment is its payer's own.
    """

    def describe(self) -> str:
        return "the action pays a Favor cost"

    def perform(self, game: GameState) -> list[GameEvent]:
        if game.round.kind not in STEP_ROUNDS:
            game.action_is_favor = True
        return []


@dataclass(frozen=True, slots=True)
class GrantLobbyBonus(Effect):
    """Record a Lobby Bonus or Penalty on ``seat`` for ``duration``.

    A Penalty is a negative ``amount``: the datasheet words them as two things and the engine reads
    them as one signed adjustment, since every amount a Lobby action checks is read through the sum.
    """

    source_id: str
    seat: PlayerId
    amount: int
    duration: Lifetime

    def describe(self) -> str:
        return (
            f"{self.source_id} gives {self.seat.name} a {self.amount:+d} Lobby Bonus "
            f"({describe_lifetime(self.duration)})"
        )

    def perform(self, game: GameState) -> list[GameEvent]:
        game.ongoing.append(LobbyModifier(self.source_id, self.seat, self.amount, self.duration))
        return []


@dataclass(frozen=True, slots=True)
class AttackEffect(Effect, ABC):
    """One of the CR's three attack effects: a strength weighed against a target's stat.

    *"Target a Follower or a Personality without Followers in the current enemy army. If its Force
    is equal to or less than X, destroy it."* Ranged and Melee destroy, Fear bows, and everything
    else is shared. Who may be targeted is
    :func:`~yasuki_core.engine.rules.board.queries.attack_targets`. This is the comparison and its
    consequence.

    The base exists because the CR names it: its Combining entry uses *"attack effect"* for the
    thing being combined and *"kind of effect"* for which of the three it is, so an effect that
    reaches every attack asks for this class and one that reaches a single kind asks for a subclass.

    Attributes
    ----------
    strength : int
        The X the target's stat is compared against.
    target_id : str
        The card being attacked.
    cause : PlayerId, Rulebook or Trait
        Who or what attacked, carried onto a destruction.
    compared : Stat, optional
        The stat weighed against ``strength``. *"If a Ranged Attack effect ends up being compared
        against a different stat than Force, compare that stat against the Ranged Attack's strength
        instead"*. Read as an effective stat, so modifiers count. Default ``Stat.FORCE``.
    outcome : tuple of Effect, optional
        What happens to a target the strength reaches, in order, built from the ordinary effects.
        Default the kind's printed outcome, ``Bow`` for Fear and ``Destroy`` for the other two,
        filled in when none is given. An Interrupt replaces the effect with one whose outcome does
        more. The outcome follows the comparison through the cascade as effects of its own, so an
        Interrupt against a Bow or a Destroy is offered against what an attack does as well.
    force_of : str, optional
        The card whose Force the strength is, as "Fear equal to his Force" has it, added to
        ``strength``. Read as the attack resolves, since the effect is made then (CR, Action
        Sequence step E), and as the card last stood in play if it has left. Default None, for a
        strength the card prints as a number.
    """

    # What the card prints this effect as, which is the only thing its description needs from the
    # subclass. Abstract, so the category cannot be announced on its own, and a class attribute on
    # each kind rather than a field: it belongs to the kind, not to one announcement.
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def subject_id(self) -> str:
        return self.target_id

    strength: int
    target_id: str
    cause: Cause
    compared: Stat = Stat.FORCE
    outcome: tuple[Effect, ...] = ()
    force_of: str | None = None

    def __post_init__(self) -> None:
        if not self.outcome:
            object.__setattr__(self, "outcome", self._printed_outcome())

    @abstractmethod
    def _printed_outcome(self) -> tuple[Effect, ...]:
        """What this kind does to a target its strength reaches, as the CR prints it."""

    def describe(self) -> str:
        strength = self._strength_text(self.force_of)
        return f"{self.name} {strength} on {self.target_id}{self._compared_stat()}"

    def _strength_text(self, named: str | None) -> str:
        """The strength as printed, or as "equal to" the Force of the card ``named`` for one taken
        from a card's Force."""
        if self.force_of is None:
            return str(self.strength)
        adjusted = f" {self.strength:+d}" if self.strength else ""
        return f"equal to {named}'s Force{adjusted}"

    def _compared_stat(self) -> str:
        return "" if self.compared is Stat.FORCE else f" vs {self.compared.name}"

    def adjusted_by(self, delta: int) -> Self:
        """This attack with ``delta`` more strength."""
        return replace(self, strength=self.strength + delta)

    def perform(self, game: GameState) -> list[GameEvent]:
        """The comparison itself changes nothing. What it decides arrives as :meth:`follow_on`."""
        return []

    def reaches(self, game: GameState) -> bool:
        """Whether the strength reaches the target's compared stat, read as the attack resolves."""
        # Imported where it is used: reading an attack's strength walks the board for the cards
        # adjusting it, and that module imports this one for the attack types.
        from yasuki_core.engine.rules.attack_effects import effective_strength

        card = game.table.cards_by_id.get(self.target_id)
        return card is not None and effective_stat(game, card, self.compared) <= (
            effective_strength(game, self)
        )

    def follow_on(self, game: GameState) -> tuple[Effect, ...]:
        return self.outcome if self.reaches(game) else ()


@dataclass(frozen=True, slots=True)
class RangedAttack(AttackEffect):
    """*"A Ranged Attack represents a military effect that destroys at a distance."*"""

    name: ClassVar[str] = "ranged"

    def _printed_outcome(self) -> tuple[Effect, ...]:
        return (Destroy(self.target_id, self.cause),)


@dataclass(frozen=True, slots=True)
class MeleeAttack(AttackEffect):
    """*"Melee Attacks follow the above rules but are not considered Ranged Attacks"*. The same
    effect as a Ranged Attack, deliberately not the same type."""

    name: ClassVar[str] = "melee"

    def _printed_outcome(self) -> tuple[Effect, ...]:
        return (Destroy(self.target_id, self.cause),)


@dataclass(frozen=True, slots=True)
class Fear(AttackEffect):
    """*"Fear X" is shorthand for "Target an enemy Follower or Personality without Followers and bow
    it if its Force is equal to or lower than X."*"""

    name: ClassVar[str] = "fear"

    def narrate(self, game: GameState) -> str:
        by_id = game.table.cards_by_id
        target = by_id[self.target_id].name
        strength = self._strength_text(
            None if self.force_of is None else _named(game, self.force_of)
        )
        return f"{self.name.capitalize()} {strength} on {target}{self._compared_stat()}"

    def _printed_outcome(self) -> tuple[Effect, ...]:
        return (Bow(self.target_id),)


@dataclass(frozen=True, slots=True)
class StartDuel(Effect):
    """Have ``challenger`` challenge ``challenged`` to a duel, and open its focusing.

    A card creating a duel names the two Personalities and nothing else. No duel happens where the
    challenge is illegal or either card has left play (CR, Challenge).

    Attributes
    ----------
    challenger : str
        The id of the Personality issuing the challenge.
    challenged : str
        The id of the Personality challenged, whose seat has the first option to focus or strike.
    source_card_id : str
        The id of the card creating the duel, which the duel records so what resolves after it can
        name the source.
    """

    challenger: str
    challenged: str
    source_card_id: str

    def describe(self) -> str:
        return f"duel: {self.challenger} challenges {self.challenged}"

    def perform(self, game: GameState) -> list[GameEvent]:
        # The procedure imports this module for the effects a duel resolves, so importing it here
        # would close that cycle.
        from yasuki_core.engine.rules.duel.procedure import declare_duel

        return declare_duel(
            game,
            challenger_duelist=self.challenger,
            challenged_duelist=self.challenged,
            source=self.source_card_id,
        )


@dataclass(frozen=True, slots=True)
class BothLoseTheDuel(Effect):
    """Have both Personalities lose the duel being fought, whatever their totals come to (CR, Duel).

    Recorded on the duel and read once, as it is decided, so a card played before the strike still
    decides a duel resolved later. A no-op where no duel is being fought.
    """

    source_id: str

    def describe(self) -> str:
        return f"{self.source_id}: both Personalities lose the duel"

    def perform(self, game: GameState) -> list[GameEvent]:
        duel = game.duel_being_fought
        if duel is None:
            return []
        duel.lost_by_both = True
        return []


@dataclass(frozen=True, slots=True)
class EndDuel(Effect):
    """End the duel being fought without resolution, which is what a duelist leaving play does to it
    (CR, Duel). Nothing the duel would have done happens: there is no winner, no loser, and no
    totals. A no-op where no duel is being fought, so the state-based rule that raises it may raise
    it more than once."""

    def describe(self) -> str:
        return "end the duel without resolution"

    def perform(self, game: GameState) -> list[GameEvent]:
        # As in StartDuel: the duel's own modules import this one.
        from yasuki_core.engine.rules.duel.resolution import end_without_resolution

        if game.duel_being_fought is None:
            return []
        return end_without_resolution(game)


@dataclass(frozen=True, slots=True)
class GrantPriority(Effect):
    """Hand ``seat`` the opportunity to act in the round now open, overriding the seat that round
    started on. A card naming the first actor in a round still to open delays this to that round's
    beginning."""

    seat: PlayerId

    def describe(self) -> str:
        return f"{self.seat.name} takes the opportunity to act"

    def perform(self, game: GameState) -> list[GameEvent]:
        # The pass count goes with it: the round is being handed to a seat rather than passed on by
        # one, so the consecutive passes that would close it start again from this seat.
        game.round = replace(
            game.round, priority=self.seat, passes=0, follow_ups=None, granted_by=None
        )
        return []


@dataclass(frozen=True, slots=True)
class AdditionalAction(Effect):
    """Grant ``seat`` an additional action: once the action now resolving is done, the opportunity
    to act goes to ``seat`` instead of passing on in turn order (CR, Additional Action). The
    consecutive-pass count starts again there, so a pass taken at that opportunity is the first of
    the passes that close the round, and a pass made before the action is not counted with it.

    Attributes
    ----------
    seat : PlayerId
        The seat granted the action.
    source_id : str
        The card whose text grants it, which a client names the opportunity after.
    follow_ups : frozenset of Action or None, optional
        The actions the opportunity may be spent on, as "take an additional Battle from your target
        Ring" limits it. A pass is always allowed. Default None, for any action the round permits.
    """

    seat: PlayerId
    source_id: str
    follow_ups: frozenset[Action] | None = None

    def describe(self) -> str:
        return f"{self.seat.name} takes an additional action"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.additional_grant = AdditionalGrant(
            self.seat, self.source_id, self.follow_ups, game.round.kind
        )
        return []


@dataclass(frozen=True, slots=True)
class GrantKeyword(Effect):
    """Record a keyword grant: the ``source`` card gives ``target`` ``keyword`` for ``duration``.

    The keyword counterpart of :class:`~.GrantModifier`, for the "give your target Personality
    Cavalry" a card prints. A keyword a card carries by its own text needs no grant: that is a
    keyword handler, read off the board.
    """

    source_id: str
    target_id: str
    keyword: str
    duration: Lifetime

    @property
    def subject_id(self) -> str:
        return self.target_id

    def describe(self) -> str:
        lifetime = describe_lifetime(self.duration)
        return f"{self.source_id} gives {self.target_id} {self.keyword} ({lifetime})"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.ongoing.append(
            KeywordGrant(self.source_id, self.target_id, self.keyword, self.duration)
        )
        return []


@dataclass(frozen=True, slots=True)
class AttachCard(Effect):
    """Attach a card to a Personality, from wherever it is.

    The other half of the Equip distinction: a card that says "attach" reaches the same board as the
    Equip action without its cost, its timing or its legality (CR, Equip). A card already in play
    moves units. One elsewhere arrives on the battlefield first, and only if it may join its owner
    (CR, Join).

    Attributes
    ----------
    card_id : str
        The card to attach.
    target_id : str
        The Personality it attaches to.
    """

    card_id: str
    target_id: str

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        return f"attach {self.card_id} to {self.target_id}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        personality = game.table.cards_by_id.get(self.target_id)
        if card is None or personality is None:
            return []
        entering = not any(held is card for held in game.table.battlefield.cards)
        if entering and not may_join(game, card.owner, card):
            return []
        hand = game.table.zones[ZoneKey(card.owner, ZoneRole.HAND)]
        from_hand = any(held is card for held in hand.cards)
        if entering:
            ops.move_card(game.table, card, BATTLEFIELD, position=UNPLACED_BOARD_POS)
        ops.attach_to_personality(game.table, card, personality)
        return [EnteredPlay(self.card_id, from_hand=from_hand)] if entering else []


@dataclass(frozen=True, slots=True)
class PutIntoPlay(Effect):
    """Move ``card_id`` onto the battlefield, unplaced.

    What a card that puts itself into play does: an Edict, a Kata, a Terrain. The played card is
    not discarded afterward because it is no longer in hand (CR, Action Sequence step F).
    Does nothing for a card already there.

    Attributes
    ----------
    card_id : str
        The card entering play.
    battlefield : int, optional
        The battlefield it enters play at, for a Terrain, which stands there in no unit (CR,
        Location). Default None, which puts it in its owner's home.
    entering_under : tuple of Ongoing, optional
        Ongoing records the card enters play under, as "if you put a Ring into play, while it
        remains in play, it does not count towards an Enlightenment Victory" has it. Laid as the
        card arrives, so no state-based action reads it without them. Default none.
    """

    card_id: str
    battlefield: int | None = None
    entering_under: tuple[Ongoing, ...] = ()

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        if self.battlefield is not None:
            return f"put {self.card_id} into play at battlefield {self.battlefield}"
        return f"put {self.card_id} into play"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None or any(held is card for held in game.table.battlefield.cards):
            return []
        if not may_join(game, card.owner, card):
            return []
        hand = game.table.zones[ZoneKey(card.owner, ZoneRole.HAND)]
        from_hand = any(held is card for held in hand.cards)
        ops.move_card(game.table, card, BATTLEFIELD, position=UNPLACED_BOARD_POS)
        # Not through place_unit: a Terrain is no unit, and the presence record it keeps is of
        # units alone.
        if self.battlefield is not None:
            assert game.attack is not None and 0 <= self.battlefield < len(game.attack.battlefields)
            ops.set_location(game.table, card, Location.at_battlefield(self.battlefield))
        game.ongoing.extend(self.entering_under)
        return [EnteredPlay(self.card_id, from_hand=from_hand)]


@dataclass(frozen=True, slots=True)
class CreateToken(Effect):
    """Create a card that was never in a deck, such as "create a 1F Ashigaru Follower" or "create a
    Personality with Force equal to the target's Chi". Put it into play.

    Stamped from the token template the deck load resolved, not a copy of anything already in the
    game. Leaving play removes it from the game rather than filling a discard pile.

    Attributes
    ----------
    token_id : str
        The template to stamp it from, by token card id.
    owner : PlayerId
        The seat that will control it.
    creator_id : str
        The card creating it, which the created card is remembered by. A card that speaks about what
        it made later (e.g., "if this Holding is ever unbowed, banish the Personality") reads the
        relation rather than hunting the board for something that looks right.
    attach_to : str or None
        The Personality it arrives attached to, or None to arrive on its own. A card that names a
        target Personality creates nothing when that Personality has left play in the meantime.
    stats : tuple of (Stat, int)
        Stats the creating card fixes. The template prints these as variable. Mishime Sensei's Oni
        has "Force equal to the target's Chi", and the token print carries a ``*`` there. Each pair
        replaces that stat on the print the created card presents, so the card genuinely has the
        number rather than carrying a modifier over a printed zero. Default none, for a template
        whose whole stat line is printed.
    clan : str or None
        The clan the created card carries, for the "with your Clan Alignment" a card grants its
        creation. None leaves the template's own printed clan alone, which is what an unaligned
        controller has to give. Default None.
    banish_at_turn_end : bool
        Whether the created card is banished before the turn ends. A creation the card lends the
        player for a turn ("banish it unless you destroyed the target") is recorded as it is made,
        because by the time the turn ends there is nothing left to decide. Default False.
    recruit : bool
        Whether the created card enters play by being Recruited without further cost, as "create
        and Recruit (without further cost)" has it, where the CR otherwise enters a created card
        without being Recruited (CR, Created Cards). It waits out of play until the Recruit that
        follows its creation. Default False.
    """

    token_id: str
    owner: PlayerId
    creator_id: str
    attach_to: str | None = None
    stats: tuple[tuple[Stat, int], ...] = ()
    clan: str | None = None
    banish_at_turn_end: bool = False
    recruit: bool = False

    def __post_init__(self) -> None:
        """Raise ValueError for a Recruited creation that also attaches, since a Recruit brings a
        card into play on its own."""
        if self.recruit and self.attach_to is not None:
            raise ValueError("a Recruited creation does not arrive attached")

    def describe(self) -> str:
        fixed = [self.clan] if self.clan else []
        fixed += [f"{stat.name} {value}" for stat, value in self.stats]
        where = "" if self.attach_to is None else f" on {self.attach_to}"
        given = f" with {', '.join(fixed)}" if fixed else ""
        verb = "creates and Recruits" if self.recruit else "creates"
        return f"{self.owner.name} {verb} {self.token_id}{where}{given}"

    def perform(self, game: GameState) -> list[GameEvent]:
        personality = None
        if self.attach_to is not None:
            personality = game.table.cards_by_id.get(self.attach_to)
            if personality is None:
                return []
        # A KeyError here is a deck that reached the table without its token templates, not a card
        # doing something unusual. The load resolves every token the deck's cards can create.
        printed = game.table.creatable_tokens[self.token_id]
        if self.stats:
            printed = replace(printed, **{stat.value: value for stat, value in self.stats})
        if self.clan is not None:
            # Both fields: a reader of a card's clans takes the list when it has one, so leaving it
            # behind would keep the template aligned to whatever it was printed as.
            printed = replace(printed, clan=self.clan, clans=(self.clan,))
        dest = None if self.recruit else BATTLEFIELD
        card = ops.spawn_token(
            game.table,
            game.mint_token_id(),
            printed,
            self.owner,
            dest=dest,
            position=UNPLACED_BOARD_POS,
        )
        game.created_by[card.id] = self.creator_id
        if self.banish_at_turn_end:
            game.delayed.append((END_OF_TURN, Banish(card.id)))
        if self.recruit:
            return []
        if personality is not None:
            ops.attach_to_personality(game.table, card, personality)
        return [EnteredPlay(card.id, from_hand=False)]

    def follow_on(self, game: GameState) -> tuple[Effect, ...]:
        """The Recruit of the card just created, when it is Recruited, at no Gold."""
        if not self.recruit:
            return ()
        # The Recruit procedure imports this module for the effects it resolves, so importing it
        # here would close that cycle.
        from yasuki_core.engine.rules.rulebook.recruit import recruit_effects

        arrival = Recruit(game.last_token_id, from_province=None)
        return tuple(recruit_effects(game, arrival))


@dataclass(frozen=True, slots=True)
class PayGold(InterruptingEffect):
    """Pay gold, bowing producers to raise what the seat's pool does not already cover.

    It pauses the cascade for the seat to pick which producers to bow, so it resolves before
    whatever an ability's text sequences behind it.

    Attributes
    ----------
    seat : PlayerId
        The seat being charged.
    amount : int
        The gold to raise.
    label : str
        What the payment is for, shown in the prompt.
    target_id : str or None, optional
        The card the Gold pays for, as a Recruit's pays for the card it brings into play, for a
        producer whose yield depends on what it pays for. Default None, for a cost that pays for no
        card.
    """

    seat: PlayerId
    amount: int
    label: str
    target_id: str | None = None

    def describe(self) -> str:
        return f"{self.seat.name} pays {self.amount} gold for {self.label}"

    # Imported where they are used: pricing a payment reads the production-boost registry, whose
    # module imports this one.
    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        from yasuki_core.engine.rules.gold.payment import can_afford

        return can_afford(
            game, self.seat, self.amount, target=self._target(game), bowed_by_cost=bowed_by_cost
        )

    def request(self, game: GameState) -> DecisionRequest:
        from yasuki_core.engine.rules.gold.payment import payment_request

        return payment_request(game, self.seat, self.amount, self.label, target=self._target(game))

    def _target(self, game: GameState) -> L5RCard | None:
        return None if self.target_id is None else game.table.cards_by_id.get(self.target_id)


@dataclass(frozen=True, slots=True)
class AskAmount(InterruptingEffect):
    """Pause for the seat to name one of ``amounts``, record it as the amount the action declares,
    and hand it to a resolver, which says what the amount does.

    The ``:X:`` in a cost block is one: :func:`~.declare_amount` asks it with a resolver that
    charges the Gold (CR, Action Sequence, Good Faith). One amount on offer is nothing to choose,
    so nothing is asked.

    Attributes
    ----------
    seat : PlayerId
        The seat choosing.
    amounts : tuple of int
        The amounts on offer.
    question : str
        What the amount is for, as the seat reads it.
    resolver : str
        The registered choice resolver the chosen amount is handed to.
    source_id : str
        The card asking.
    resolver_context : tuple of str, optional
        What the cost settled before asking, carried through to the resolver. Default empty.
    """

    seat: PlayerId
    amounts: tuple[int, ...]
    question: str
    resolver: str
    source_id: str
    resolver_context: tuple[str, ...] = ()

    def describe(self) -> str:
        return f"{self.seat.name} is asked: {self.question}"

    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        """Nothing to choose from is nothing to pay."""
        return bool(self.amounts)

    def pauses(self, game: GameState) -> bool:
        """One amount on offer is nothing to choose, so nothing is asked."""
        return len(self.amounts) != 1

    def perform(self, game: GameState) -> list[GameEvent]:
        game.amount_declared = self.amounts[0]
        return []

    def follow_on(self, game: GameState) -> tuple[Effect, ...]:
        return tuple(self.answered(game, self.amounts[0]))

    def answered(self, game: GameState, amount: int) -> list[Effect]:
        """What naming ``amount`` resolves, as the resolver makes it of the board as it stands."""
        from yasuki_core.engine.rules.triggers import resolve_choice

        chosen = (str(amount),)
        return resolve_choice(
            game, self.resolver, self.source_id, chosen, self.seat, self.resolver_context
        )

    def request(self, game: GameState) -> DecisionRequest:
        return ChooseAmount(
            seat=self.seat,
            candidates=tuple(str(amount) for amount in self.amounts),
            question=self.question,
            resolver=self.resolver,
            source_id=self.source_id,
            resolver_context=self.resolver_context,
        )


@dataclass(frozen=True, slots=True)
class AlternateEffects(InterruptingEffect):
    """Ask ``seat`` which of ``options`` happens, as an alternate effect ("bow or destroy it") has
    it, when it comes up to resolve, and commit the one chosen (CR, Choices).

    The first of a :class:`To` may be one, so what depends on it follows only if the chosen effect
    actually happened (CR, Independence of Effects). It would happen while any of its options
    would, which is what the Interrupt step reads of what depends on it.

    Attributes
    ----------
    seat : PlayerId
        The seat choosing: the player taking the action, the CR's default where the card names none.
    options : tuple of Effect
        The alternatives, in print order.
    wordings : tuple of str
        Each alternative as the seat reads it, in the same order.
    question : str
        What is being chosen.
    source_id : str
        The card whose text offers the choice.
    """

    seat: PlayerId
    options: tuple[Effect, ...]
    wordings: tuple[str, ...]
    question: str
    source_id: str

    def __post_init__(self) -> None:
        """Raise ValueError unless each alternative has one wording."""
        if len(self.options) != len(self.wordings):
            raise ValueError("each alternative needs one wording")

    def describe(self) -> str:
        return f"{self.seat.name} chooses: {' or '.join(self.wordings)}"

    def would_happen(self, game: GameState) -> bool:
        return any(option.would_happen(game) for option in self.options)

    def answered(self, choices: tuple[str, ...]) -> Effect:
        return self.options[self.wordings.index(choices[0])]

    def possible_answers(self) -> tuple[Effect, ...]:
        return self.options

    def request(self, game: GameState) -> DecisionRequest:
        return ChooseOption(
            seat=self.seat,
            candidates=self.wordings,
            question=self.question,
            resolver=None,
            source_id=self.source_id,
        )


@dataclass(frozen=True, slots=True)
class AskOption(InterruptingEffect):
    """Pause for the seat to pick one of the outcomes a card spells out, then hand the choice to a
    resolver.

    For the "gain or lose", "a target player" a card leaves to its controller: the board cannot
    settle it, so the seat is asked and the resolver turns the answer back into effects.

    Attributes
    ----------
    seat : PlayerId
        The seat choosing.
    options : tuple of str
        The outcomes on offer, as the seat reads them.
    question : str
        What is being chosen.
    resolver : str
        The registered choice resolver the chosen option is handed to.
    source_id : str
        The card offering the choice.
    resolver_context : tuple of str, optional
        What an earlier step of the same choice settled, carried through to the resolver. Default
        empty.
    minimum : int, optional
        The fewest outcomes the seat may pick. Default 1.
    maximum : int, optional
        The most outcomes the seat may pick, as "either or both" allows two. Default 1.
    """

    seat: PlayerId
    options: tuple[str, ...]
    question: str
    resolver: str
    source_id: str
    resolver_context: tuple[str, ...] = ()
    minimum: int = 1
    maximum: int = 1

    def describe(self) -> str:
        return f"{self.seat.name} is asked: {self.question}"

    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        """Nothing to choose from is nothing to choose."""
        return bool(self.options)

    def request(self, game: GameState) -> DecisionRequest:
        return ChooseOption(
            seat=self.seat,
            candidates=self.options,
            question=self.question,
            resolver=self.resolver,
            source_id=self.source_id,
            resolver_context=self.resolver_context,
            minimum=self.minimum,
            maximum=self.maximum,
        )


@dataclass(frozen=True, slots=True)
class DeclareOptions(Effect):
    """Declare ``options`` for the action now resolving, the outcomes its cost was paid for, which
    its effects read as ``game.options_declared`` (CR, Action Sequence step B). Part of the cost a
    resolver turns an answer into, so only the action's own question declares anything."""

    options: tuple[str, ...]

    def describe(self) -> str:
        return f"declare {', '.join(self.options)}"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.options_declared = self.options
        return []


@dataclass(frozen=True, slots=True)
class ExemptFromResolutionBow(Effect):
    """The resolution of the battle at ``battlefield`` does not bow ``seat``'s units there (CR,
    After Resolution 0.1). Nothing happens outside an attack.

    Attributes
    ----------
    seat : PlayerId
        The seat whose units keep standing.
    battlefield : int
        The battlefield whose battle it is.
    """

    seat: PlayerId
    battlefield: int

    def describe(self) -> str:
        return f"the resolution at battlefield {self.battlefield} does not bow {self.seat.name}"

    def perform(self, game: GameState) -> list[GameEvent]:
        attack = game.attack
        if attack is not None:
            exempt = attack.battlefields[self.battlefield].bow_exempt
            attack.amend(self.battlefield, bow_exempt=exempt | {self.seat})
        return []


@dataclass(frozen=True, slots=True)
class Bow(Effect):
    """Bow a card, announcing the change. One already bowed announces nothing."""

    card_id: str

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        return f"bow {self.card_id}"

    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        """An already-bowed card cannot bow again."""
        card = game.table.cards_by_id.get(self.card_id)
        return card is not None and not card.bowed

    def would_happen(self, game: GameState) -> bool:
        card = game.table.cards_by_id.get(self.card_id)
        return card is not None and not card.bowed

    def perform(self, game: GameState) -> list[GameEvent]:
        if not self.would_happen(game):
            return []
        game.table.cards_by_id[self.card_id].bow()
        return [Bowed(self.card_id)]


@dataclass(frozen=True, slots=True)
class TurnOver(Effect):
    """Turn a two-faced card over to whichever face it is not showing.

    It names no face, since a Stronghold that a card already turned to its front goes back to its
    back (ShE datasheet, The Inheritance Rule).
    """

    card_id: str

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        return f"turn {self.card_id} over"

    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        """A card with no back face has nothing to turn over to."""
        card = game.table.cards_by_id.get(self.card_id)
        return card is not None and card.printed.back_card_id is not None

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is not None:
            card.flip_face()
        return []


@dataclass(frozen=True, slots=True)
class Straighten(Effect):
    """Straighten (unbow) a card. Announces the change, which a card that watches for its own
    straightening reads. One already standing, or forbidden to straighten, announces nothing."""

    card_id: str

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        return f"straighten {self.card_id}"

    def would_happen(self, game: GameState) -> bool:
        card = game.table.cards_by_id.get(self.card_id)
        return card is not None and card.bowed and self.card_id not in game.straighten_delayed

    def perform(self, game: GameState) -> list[GameEvent]:
        if not self.would_happen(game):
            return []
        game.table.cards_by_id[self.card_id].unbow()
        return [Straightened(self.card_id)]


@dataclass(frozen=True, slots=True)
class Dishonor(Effect):
    """Dishonor a Personality (CR, Honorable and Dishonorable). Announces the change, naming
    ``cause`` as who or what dishonored him. Only a Personality can be dishonorable, so any other
    card, and one already dishonorable, announces nothing.

    Attributes
    ----------
    card_id : str
        The Personality to dishonor.
    cause : PlayerId, Rulebook or Trait
        Who or what dishonored him: the seat whose card did, or the rule that demanded it.
    """

    card_id: str
    cause: Cause

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        return f"dishonor {self.card_id}"

    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        """A dishonorable Personality cannot be dishonored again."""
        return self._target(game) is not None

    def perform(self, game: GameState) -> list[GameEvent]:
        card = self._target(game)
        if card is None:
            return []
        card.dishonor()
        return [Dishonored(self.card_id, self.cause)]

    def _target(self, game: GameState) -> L5RCard | None:
        """The honorable Personality this would dishonor, or None when there is nothing to do."""
        card = game.table.cards_by_id.get(self.card_id)
        if card is None or not isinstance(card.printed, PersonalityPrint) or card.dishonorable:
            return None
        return card


@dataclass(frozen=True, slots=True)
class Rehonor(Effect):
    """Rehonor a dishonorable Personality (CR, Rehonoring). Announces the change, which a card that
    reacts to a rehonoring reads. One already honorable announces nothing.

    Attributes
    ----------
    card_id : str
        The Personality to rehonor.
    negatable : bool, optional
        Whether a negation can stop it. False for a rehonoring the rules say cannot be negated, as
        seppuku's. Default True.
    """

    card_id: str
    negatable: bool = True

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        return f"rehonor {self.card_id}"

    def is_negatable(self, game: GameState) -> bool:
        return self.negatable

    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        """An honorable Personality cannot be rehonored."""
        card = game.table.cards_by_id.get(self.card_id)
        return card is not None and card.dishonorable

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None or not card.dishonorable:
            return []
        card.rehonor()
        return [Rehonored(self.card_id)]


def seppuku(card_id: str, cause: Cause) -> list[Effect]:
    """The effects of a Personality committing seppuku: rehonor him, then destroy him (CR,
    Seppuku). Two effects rather than one, so each passes through the Interrupt step on its own,
    and the Personality's own reaction to his rehonoring resolves while he is still in play. The CR
    adds that neither can be negated, so both are built not negatable, against a lasting negation
    and an Interrupt's alike.

    Parameters
    ----------
    card_id : str
        The Personality committing seppuku.
    cause : PlayerId, Rulebook or Trait
        Who or what directed it: the seat whose card did, or the rule that demanded it.
    """
    return [
        Rehonor(card_id, negatable=False),
        Destroy(card_id, cause, negatable=False),
    ]


@dataclass(frozen=True, slots=True)
class BanishTopFate(Effect):
    """Banish the top card of ``seat``'s Fate deck. A no-op if the deck is empty."""

    seat: PlayerId

    def describe(self) -> str:
        return f"banish the top of {self.seat.name}'s fate deck"

    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        """An empty Fate deck has nothing to banish."""
        return bool(game.table.decks[DeckKey(self.seat, Side.FATE)].cards)

    def perform(self, game: GameState) -> list[GameEvent]:
        deck = game.table.decks[DeckKey(self.seat, Side.FATE)]
        if deck.cards:
            ops.move_card(game.table, deck.cards[-1], ZoneKey(self.seat, ZoneRole.FATE_BANISH))
        return []


@dataclass(frozen=True, slots=True)
class LookAtTop(Effect):
    """Let ``seat`` look at the top ``count`` cards of ``deck``, opening a :class:`~.Look`.

    The cards stay where they are: the seat reads them and the decisions that follow say where each
    goes. Each card gains the seat as a peeker. A deck shorter than ``count`` shows what it has.

    Attributes
    ----------
    seat : PlayerId
        The seat looking.
    deck : DeckKey
        The deck looked at.
    count : int
        How many cards from the top.
    """

    seat: PlayerId
    deck: DeckKey
    count: int

    def describe(self) -> str:
        side = self.deck.side.name.lower()
        return f"{self.seat.name} looks at the top {self.count} of {self.deck.owner.name}'s {side} deck"

    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        """An empty deck has nothing to look at."""
        return bool(game.table.decks[self.deck].cards)

    def perform(self, game: GameState) -> list[GameEvent]:
        """Raise RuntimeError if a look is already open: two at once would overwrite each other, and
        the first card's EndLook would close the second's."""
        if game.look is not None:
            raise RuntimeError("a look is already open")
        seen = list(reversed(game.table.decks[self.deck].peek(self.count)))
        for card in seen:
            game.show_to(card, self.seat)
        game.look = Look(self.seat, self.deck, tuple(card.id for card in seen))
        return []


@dataclass(frozen=True, slots=True)
class LookAtHand(Effect):
    """Let ``seat`` read every card in ``holder``'s hand, as "look at the player's hand" has it.

    The cards keep the seat as a peeker once the reading is done, as a deck's do after a
    :class:`~.LookAtTop`: a seat cannot unsee a card. Shuffling one into a deck scrubs it.

    Attributes
    ----------
    seat : PlayerId
        The seat looking.
    holder : PlayerId
        The seat whose hand is read.
    """

    seat: PlayerId
    holder: PlayerId

    def describe(self) -> str:
        return f"{self.seat.name} looks at {self.holder.name}'s hand"

    def perform(self, game: GameState) -> list[GameEvent]:
        for card in game.table.zones[ZoneKey(self.holder, ZoneRole.HAND)].cards:
            game.show_to(card, self.seat)
        return []


@dataclass(frozen=True, slots=True)
class EndLook(Effect):
    """Close the open :class:`~.Look`, once the last question about its cards is answered.

    The cards keep their peeker: a card that stayed in the deck is still one the seat has read, and
    entering a deck from anywhere else scrubs it anyway.
    """

    def describe(self) -> str:
        return "the look ends"

    def is_interruptible(self, game: GameState) -> bool:
        return False  # bookkeeping, not something a card can act against

    def perform(self, game: GameState) -> list[GameEvent]:
        game.look = None
        return []


@dataclass(frozen=True, slots=True)
class PlaceOnDeck(Effect):
    """Put ``card_ids`` on one end of ``deck`` in the order given, each outside the one before it,
    so the last named ends outermost: on top for the top, at the very bottom for the bottom. A card
    that no longer exists is skipped.

    Attributes
    ----------
    card_ids : tuple of str
        The cards, in placement order.
    deck : DeckKey
        The deck they land in.
    to_bottom : bool, optional
        Whether they go under the deck rather than on top of it. Default False.
    """

    card_ids: tuple[str, ...]
    deck: DeckKey
    to_bottom: bool = False

    def describe(self) -> str:
        end = "the bottom" if self.to_bottom else "the top"
        side = self.deck.side.name.lower()
        return f"put {len(self.card_ids)} on {end} of {self.deck.owner.name}'s {side} deck"

    def perform(self, game: GameState) -> list[GameEvent]:
        for card_id in self.card_ids:
            card = game.table.cards_by_id.get(card_id)
            if card is not None:
                _move_card(game, card, self.deck, to_bottom=self.to_bottom)
        return []


@dataclass(frozen=True, slots=True)
class MoveToDeck(Effect):
    """Move a card into a deck at a stated depth, counting from whichever end names it.

    Give exactly one of ``from_top`` and ``from_bottom``. Depths are zero-based: ``from_top=0`` is
    the top card, ``from_bottom=0`` the bottom. A depth past the far end clamps to that end, so a
    deck of two asked for ``from_top=9`` takes the card at the bottom rather than raising. A card
    that no longer exists is a no-op.

    Attributes
    ----------
    card_id : str
        The card to move.
    deck : DeckKey
        The deck it lands in.
    from_top : int, optional
        Depth measured from the top of the deck. Default None.
    from_bottom : int, optional
        Depth measured from the bottom of the deck. Default None.
    """

    card_id: str
    deck: DeckKey
    from_top: int | None = None
    from_bottom: int | None = None

    @property
    def subject_id(self) -> str:
        return self.card_id

    def __post_init__(self) -> None:
        """Raise ValueError unless exactly one non-negative depth names an end."""
        if (self.from_top is None) == (self.from_bottom is None):
            raise ValueError("MoveToDeck takes exactly one of from_top or from_bottom")
        depth = self.from_top if self.from_top is not None else self.from_bottom
        if depth < 0:
            raise ValueError(f"MoveToDeck depth cannot be negative, got {depth}")

    def describe(self) -> str:
        end, depth = (
            ("top", self.from_top) if self.from_top is not None else ("bottom", self.from_bottom)
        )
        side = self.deck.side.name.lower()
        return f"move {self.card_id} into {self.deck.owner.name}'s {side} deck, {depth} from {end}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None:
            return []
        # The card leaves wherever it is before it lands, so a card already in this deck must not
        # count itself when its depth is measured.
        cards = game.table.decks[self.deck].cards
        landing_size = len(cards) - (1 if any(held is card for held in cards) else 0)
        index = self.from_bottom if self.from_bottom is not None else landing_size - self.from_top
        _move_card(game, card, self.deck, deck_index=index)
        return []


@dataclass(frozen=True, slots=True)
class GainGold(Effect):
    """Add ``amount`` gold to ``seat``'s pool: gold produced outside a payment (a card that produces
    gold on entry), transient and cleared at the end of the phase."""

    seat: PlayerId
    amount: int

    def describe(self) -> str:
        return f"{self.seat.name} gains {self.amount} gold"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.add_gold(self.seat, self.amount)
        return []


@dataclass(frozen=True, slots=True)
class LoseGame(Effect):
    """End the game, with ``seat`` the loser and the last player left the winner.

    Attributes
    ----------
    seat : PlayerId
        The seat that has lost.
    reason : str
        Why, worded for a player.
    victory : str
        What the surviving seat has thereby won, worded for a player.
    """

    seat: PlayerId
    reason: str
    victory: str

    def describe(self) -> str:
        return f"{self.seat.name} loses: {self.reason}"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.lose(self.seat, self.reason, self.victory)
        return []


@dataclass(frozen=True, slots=True)
class WinGame(Effect):
    """End the game, with ``seat`` the winner and no loser.

    Attributes
    ----------
    seat : PlayerId
        The seat that has won.
    reason : str
        What it won, worded for a player.
    """

    seat: PlayerId
    reason: str

    def describe(self) -> str:
        return f"{self.seat.name} wins: {self.reason}"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.win(self.seat, self.reason)
        return []


# Cards whose controller loses less Honor from their own cards' effects, keyed on printed id, each
# mapping the size of such a loss to what is left of it: "You lose 1 Honor less from your cards",
# or "You do not lose Honor from your cards' effects", which leaves nothing. A rulebook loss, such
# as a dishonorable Personality's destruction, is no card's effect and is not reduced (CR,
# Dishonorable).
HonorLossReduction = Callable[[int], int]
HONOR_LOSS_REDUCTIONS: HandlerRegistry[HonorLossReduction] = HandlerRegistry(
    "honor loss reductions", "already reduces its controller's Honor losses"
)
register_honor_loss_reduction = HONOR_LOSS_REDUCTIONS.make_register()


def honor_loss_reduced_by(amount: int) -> HonorLossReduction:
    """The reduction of "You lose ``amount`` Honor less from your cards"."""

    def reduce(loss: int) -> int:
        return loss - amount

    return reduce


def no_honor_lost(loss: int) -> int:
    """The reduction of "You do not lose Honor from your cards' effects"."""
    return 0


@dataclass(frozen=True, slots=True)
class GainHonor(Effect):
    """Move ``seat``'s Family Honor by ``amount``. Negative loses honor. The two directions are one
    effect because the rules treat them as one dial.

    Attributes
    ----------
    seat : PlayerId
        The seat whose Honor moves.
    amount : int
        The signed change, before any Interrupt.
    adjustment : int, optional
        The net change the Interrupts taken against this change make to its size, applied once
        when it performs so that no run of Interrupts can carry it through zero and reverse it.
        Default 0.
    personalities : tuple of str, optional
        The Personalities the gain's action or trait targeted or came from. A gain owed while one
        of them is ``seat``'s and dishonorable rehonors him instead, one rehonoring standing in for
        the whole gain (CR, Rehonoring 0.1 and 0.2). A handler whose action rehonors him as one of
        its own effects leaves this empty, since the CR substitutes only where rehonoring "is not
        one of that action or trait's effects". Default empty.
    source_id : str, optional
        The card whose effect this is, so a reduction of a seat's own cards' losses can tell
        them from anyone else's. Default None, a rulebook change.
    """

    seat: PlayerId
    amount: int
    adjustment: int = 0
    personalities: tuple[str, ...] = ()
    source_id: str | None = None

    @property
    def adjusted(self) -> int:
        return adjusted_honor_change(self.amount, self.adjustment)

    def adjusted_by(self, delta: int) -> Self:
        """This change with its size moved ``delta`` further, by :func:`adjusted_honor_change`."""
        return replace(self, adjustment=self.adjustment + delta)

    def describe(self) -> str:
        return self._describe(self.seat.name)

    def narrate(self, game: GameState) -> str:
        return self._describe(game.table.seats[self.seat].name)

    def _describe(self, whose: str) -> str:
        amount = self.adjusted
        verb = "gains" if amount >= 0 else "loses"
        return f"{whose} {verb} {abs(amount)} honor"

    def is_interruptible(self, game: GameState) -> bool:
        # A change of zero is not a gain or loss (CR, Honor Gains and Losses), and neither is a loss
        # a card says its seat does not take, so there is nothing to interrupt.
        return self._reduced(game, self.amount) != 0

    def perform(self, game: GameState) -> list[GameEvent]:
        amount = self._reduced(game, self.adjusted)
        if amount == 0:
            return []
        rehonored = self._substituted_for(game) if amount > 0 else []
        if rehonored:
            for card in rehonored:
                card.rehonor()
            return [Rehonored(card.id) for card in rehonored]
        if not ops.set_honor(game.table, self.seat, delta=amount):
            return []
        if amount < 0 and not self._from_own_cards(game):
            ops.set_lost_honor_from_elsewhere(game.table, self.seat)
        return [HonorChanged(self.seat, amount)]

    def _from_own_cards(self, game: GameState) -> bool:
        """Whether the change comes from a card ``seat`` controls. False for a rulebook change,
        which is no card's effect (CR, Dishonorable)."""
        source = game.table.cards_by_id.get(self.source_id) if self.source_id else None
        return source is not None and source.owner is self.seat

    def _reduced(self, game: GameState, amount: int) -> int:
        """``amount``, a loss reduced by the cards ``seat`` controls that reduce the losses its own
        cards' effects cost it. A loss is never reduced past zero (CR, Honor Gains and Losses)."""
        if amount >= 0 or not self._from_own_cards(game):
            return amount
        loss = -amount
        for card in game.table.battlefield.cards:
            reduce = HONOR_LOSS_REDUCTIONS.get(card.printed_id)
            if reduce is not None and card.owner is self.seat:
                loss = reduce(loss)
        return -max(0, loss)

    def _substituted_for(self, game: GameState) -> list[L5RCard]:
        """The seat's own dishonorable Personalities among ``personalities``, whose rehonoring
        stands in for the gain."""
        return [
            card
            for card_id in self.personalities
            if (card := game.table.cards_by_id.get(card_id)) is not None
            and card.owner is self.seat
            and card.dishonorable
        ]


def adjusted_honor_change(amount: int, adjustment: int) -> int:
    """``amount`` with ``adjustment`` applied to its size, keeping its direction.

    A gain stays a gain and a loss a loss however far it is reduced, and neither goes below zero
    (CR, Honor Gains and Losses). A positive ``adjustment`` makes the gain or loss larger.
    """
    size = max(0, abs(amount) + adjustment)
    return size if amount > 0 else -size


@dataclass(frozen=True, slots=True)
class Adjustment:
    """An Interrupt's adjustment to one effect of the action, bound to the effect as the forecast
    showed it and applied as it comes up to resolve. Two Courage discards on one Fear are two of
    these, each adjusting what the one before left. Plain data, so a game with one pending compares
    equal to its replay.

    Attributes
    ----------
    bound : AttackEffect or GainHonor
        The action's effect, as first handed to step E, that the Interrupt answered.
    delta : int
        The adjustment chosen.
    """

    bound: AttackEffect | GainHonor
    delta: int

    def answers(self, effect: Effect) -> bool:
        return effect == self.bound

    def apply(self, game: GameState, effect: Effect) -> Effect:
        """``effect`` adjusted, or left as it is where an earlier Interrupt made it something with
        nothing to adjust."""
        if isinstance(effect, AttackEffect | GainHonor):
            return effect.adjusted_by(self.delta)
        return effect


@dataclass(frozen=True, slots=True)
class AdjustPending(Effect):
    """Bind an :class:`Adjustment` of ``delta`` to ``bound``, an effect of the action held at the
    Interrupt step, to apply when that effect comes up to resolve.

    Attributes
    ----------
    bound : AttackEffect or GainHonor
        The action's effect, as first handed to step E.
    delta : int
        What to add to its strength or to the size of its Honor change.
    """

    bound: AttackEffect | GainHonor
    delta: int

    def describe(self) -> str:
        return f"{self.bound.describe()}, adjusted by {self.delta:+d}"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.modifications.append(Adjustment(self.bound, self.delta))
        return []


@dataclass(frozen=True, slots=True)
class DelayStraighten(Effect):
    """Forbid ``card_id`` from straightening until ``until`` in its controller's next Action Phase.

    Blocks any attempt to straighten the card while it holds, not just the turn-start straighten.
    Imposed, unlike the printed "May remain bowed" its controller chooses each turn.

    Attributes
    ----------
    card_id : str
        The card forbidden to straighten.
    until : Moment, optional
        The edge of that Action Phase that lifts the prohibition, its beginning or its end. Default
        its end, as "until after their next Action Phase" reads.
    """

    card_id: str
    until: Moment = END_OF_ACTION_PHASE

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        if self.until == BEGINNING_OF_ACTION_PHASE:
            return f"{self.card_id} may not straighten until its next Action Phase begins"
        return f"{self.card_id} may not straighten until after its next Action Phase"

    def perform(self, game: GameState) -> list[GameEvent]:
        """Raise ValueError for a moment other than the Action Phase's two edges, which is all the
        turn lifts delays at."""
        if self.until not in (BEGINNING_OF_ACTION_PHASE, END_OF_ACTION_PHASE):
            raise ValueError(f"a straighten delay cannot lift at {self.until}")
        game.straighten_delayed[self.card_id] = StraightenDelay(game.turn, self.until)
        return []


@dataclass(frozen=True, slots=True)
class Recruit(Effect):
    """Bring ``card_id`` into play as a Recruit, in its entry state and with a Fortification
    attached to a Province (CR, Recruit). What its arrival is followed by resolves behind the
    reactions to it: its Sincerity tokens are removed, a Proclaim adds its Personal Honor, and the
    Province it left is refilled.

    A card put into play is not Recruited, and only this effect's arrival reports ``recruited``.

    Attributes
    ----------
    card_id : str
        The card being Recruited.
    from_province : ZoneKey or None
        The Province the card is Recruited from, or None for a card Recruited from anywhere else,
        which leaves no Province to refill.
    fortifies : ZoneKey or None, optional
        The Province a Fortification Recruited from anywhere else attaches to, as its controller
        chose (CR, Fortification). Default None.
    renew : bool, optional
        Whether the vacated Province refills face-up whatever the card's own Renew keyword says.
        Default False.
    proclaim : bool, optional
        Whether the Recruit is Proclaimed. Default False.
    """

    card_id: str
    from_province: ZoneKey | None
    fortifies: ZoneKey | None = None
    renew: bool = False
    proclaim: bool = False

    @property
    def subject_id(self) -> str:
        return self.card_id

    def describe(self) -> str:
        return f"recruit {self.card_id}"

    def would_happen(self, game: GameState) -> bool:
        """Whether the card may enter play: Unique and Singular can keep it out, its own "May only
        be Recruited by" text can, and so can a Personality's Honor Requirement.

        The Honor Requirement is checked here rather than only where the rulebook offers a Recruit,
        so a card that Recruits by returning this effect meets it too.
        """
        # The Recruit procedure imports this module for the effects it resolves, so importing it
        # at the top would close that cycle.
        from yasuki_core.engine.rules.rulebook.recruit import meets_honor_requirement

        card = game.table.cards_by_id[self.card_id]
        if not may_join(game, card.owner, card) or not may_recruit(game, card.owner, card):
            return False
        return meets_honor_requirement(game, card)

    def perform(self, game: GameState) -> list[GameEvent]:
        # The Recruit procedure imports this module for the effects it resolves, so importing it
        # here would close that cycle.
        from yasuki_core.engine.rules.rulebook.recruit import bring_into_play

        if not self.would_happen(game):
            return []
        return bring_into_play(game, self)

    def proclamation(self, game: GameState) -> tuple[Effect, ...]:
        """The Proclaim's Honor gain, the one part of what follows the arrival that is the Recruit
        action's own (CR, Proclaim), read on the board as it stands. Empty without a Proclaim."""
        from yasuki_core.engine.rules.rulebook.recruit import proclamation_effects

        return tuple(proclamation_effects(game, self))

    def follow_on(self, game: GameState) -> tuple[Effect, ...]:
        """What the arrival is followed by, behind the reactions to it. Nothing when the card did
        not arrive."""
        from yasuki_core.engine.rules.rulebook.recruit import effects_after_entering_play

        card = game.table.cards_by_id[self.card_id]
        if not any(held is card for held in game.table.battlefield.cards):
            return ()
        return tuple(effects_after_entering_play(game, self))


@dataclass(frozen=True, slots=True)
class RefillProvince(Effect):
    """Refill a Province that a card has left, if it is still short.

    The conditional is the rule, not a guard: a Province is refilled "unless something else has
    refilled it", so a reaction that filled the gap first leaves this a no-op. Deferred behind the
    reactions to the card leaving, which is where the rules place it.

    Attributes
    ----------
    zone : ZoneKey
        The Province to refill.
    face_up : bool, optional
        Whether the card arrives face-up, as a Renew refill does. Default False.
    """

    zone: ZoneKey
    face_up: bool = False

    def describe(self) -> str:
        face = " face-up" if self.face_up else ""
        return f"refill {self.zone.owner.name} province {self.zone.idx}{face}"

    def perform(self, game: GameState) -> list[GameEvent]:
        province = game.table.zones.get(self.zone)
        if province is None or not province.has_capacity():
            return []
        ops.fill_province(game.table, self.zone.owner, province, face_up=self.face_up)
        return []


@dataclass(frozen=True, slots=True)
class RevealProvinces(Effect):
    """Turn every face-down card in ``seat``'s Provinces face-up, announcing each one it turns. A
    card already face-up raises nothing, since nothing turned."""

    seat: PlayerId

    def describe(self) -> str:
        return f"reveal {self.seat.name}'s provinces"

    def perform(self, game: GameState) -> list[GameEvent]:
        return [Revealed(card_id) for card_id in ops.reveal_provinces(game.table, self.seat)]


@dataclass(frozen=True, slots=True)
class CounterOnAttachedProvince(Effect):
    """Put counters on whichever Province ``card_id`` is attached to.

    The Province is read when this resolves rather than named up front: a card that says "give its
    Province a token" is played before its Fortification has one, and which Province that is may be
    a choice the seat has not made yet. Does nothing if the card is attached to none.

    Attributes
    ----------
    card_id : str
        The Fortification whose Province takes the counters.
    counter : Counter
        The counter to add.
    delta : int
        How many to add.
    """

    card_id: str
    counter: Counter
    delta: int

    def describe(self) -> str:
        return f"{self.delta:+d} {self.counter.name} on {self.card_id}'s province"

    def perform(self, game: GameState) -> list[GameEvent]:
        province = game.table.province_attachments.get(self.card_id)
        if province is not None:
            ops.adjust_province_counter(game.table, province, self.counter.key, self.delta)
        return []


@dataclass(frozen=True, slots=True)
class Unpayable(Effect):
    """A cost that can never be paid, so the ability holding it is never offered. Resolving one
    raises an exception. Reaching it means the legality check that should have withheld the ability
    did not run.

    Attributes
    ----------
    reason : str
        Why the cost cannot be met, for the cascade trace.
    """

    reason: str

    def describe(self) -> str:
        return f"unpayable: {self.reason}"

    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        return False

    def perform(self, game: GameState) -> list[GameEvent]:
        raise RuntimeError(f"resolved an unpayable cost: {self.reason}")


@dataclass(frozen=True, slots=True)
class ApplyEffects:
    """Resolve ``effects`` once the work queued above it on the stack has finished, such as a step
    of a procedure that follows the one under way, or an Interrupt's effects behind its payment.

    Attributes
    ----------
    effects : tuple of Effect
        The effects to resolve, in order.
    provenance : Provenance, optional
        Where the effects came from. Default a rulebook procedure's, neither an action's own nor a
        trigger's.
    """

    effects: tuple[Effect, ...]
    provenance: Provenance = Provenance()

    def resume(self, game: GameState) -> None:
        # The cascade imports this module, so the one module this item drives cannot be imported at
        # the top without closing that cycle.
        from yasuki_core.engine.rules import triggers

        if self.provenance.interruptible:
            triggers.resolve_action_effects(game, list(self.effects), provenance=self.provenance)
        else:
            triggers.resolve_effects(game, list(self.effects), provenance=self.provenance)


@dataclass(frozen=True, slots=True)
class Simultaneously(Effect):
    """Apply ``effects`` as one occurrence, so nothing reacts until every one has happened.

    For one piece of text, or one rule, acting on several cards at once: "the Attacker and
    Defender each destroy all units in the enemy army" (CR, Battle Resolution), as against
    sentences in sequence, which "occur in the order they are written" (CR, Order of Effects). Each
    member is checked, modified and negated as it would be alone.

    Attributes
    ----------
    effects : tuple of Effect
        What happens at once, in the order they are applied.
    """

    effects: tuple[Effect, ...]

    def describe(self) -> str:
        return f"at once: {len(self.effects)} effects"

    def is_interruptible(self, game: GameState) -> bool:
        return False

    def is_negatable(self, game: GameState) -> bool:
        return False

    def perform(self, game: GameState) -> list[GameEvent]:
        """Apply every member in turn. The cascade handles a group itself, applying each member
        through the checks any effect meets, so this runs only when a group is applied outside
        it."""
        return [event for effect in self.effects for event in effect.perform(game)]


@dataclass(frozen=True, slots=True)
class To(Effect):
    """Apply ``first``, then ``contingent`` only if ``first`` actually happened: "effects linked by
    the word "to" mean that the second effect depends on the first effect actually happening" (CR,
    Independence of Effects). ``first`` happened when it would change something as it commits
    (:meth:`~.Effect.would_happen`) and commits as itself: one negated, or replaced by an Interrupt
    with a different effect or the same effect on a different card, did not. One an Interrupt only
    adjusted did. What reacts to ``first`` resolves before ``contingent`` applies.

    Raise ``TypeError`` if ``first`` asks a question or holds other effects, which the walk could
    not tell happened, unless the question is answered in place, as :class:`AlternateEffects` is:
    what the answer makes of it is what happened.

    Attributes
    ----------
    first : Effect
        The effect the rest depends on, such as the discard in "discard a card to draw a card".
    contingent : tuple of Effect
        What applies once ``first`` has happened, in order.
    """

    first: Effect
    contingent: tuple[Effect, ...]

    def __post_init__(self) -> None:
        if isinstance(self.first, InterruptingEffect) and self.first.answers_in_place:
            return
        if isinstance(self.first, InterruptingEffect | Simultaneously | To | Attributed):
            raise TypeError(f"{type(self.first).__name__} cannot be what another effect depends on")

    def describe(self) -> str:
        return f"{self.first.describe()} to: {len(self.contingent)} effects"

    def is_interruptible(self, game: GameState) -> bool:
        return False

    def is_negatable(self, game: GameState) -> bool:
        return False

    def perform(self, game: GameState) -> list[GameEvent]:
        """Apply ``first`` and, if it would change something, ``contingent``. The cascade handles
        the link itself, applying each effect through the checks any effect meets, so this runs
        only when it is applied outside it."""
        happens = self.first.would_happen(game)
        raised = self.first.perform(game)
        if not happens:
            return raised
        return [*raised, *(event for effect in self.contingent for event in effect.perform(game))]


@dataclass(frozen=True, slots=True)
class Ask(InterruptingEffect):
    """Put a yes/no question to a seat, and hand ``subjects`` to the resolver if it answers yes.

    The question names what is being asked so the seat reads it rather than inferring it from a
    board selection. Use this for an optional effect whose subject is already settled. A genuine
    pick among several cards is a :class:`~.Choose`.

    Attributes
    ----------
    seat : PlayerId
        The seat answering.
    question : str
        The question as the seat reads it, naming the cards it concerns.
    resolver : str
        The registered choice resolver naming what a yes does.
    subjects : tuple of str
        The card ids passed to the resolver on yes. It receives none on no.
    source_id : str, optional
        A card id handed to the resolver as its context. Default None.
    declinable : bool, optional
        Whether no is an answer, for an option the seat has already committed to by acting. Default
        True.
    """

    seat: PlayerId
    question: str
    resolver: str
    subjects: tuple[str, ...] = ()
    source_id: str | None = None
    declinable: bool = True

    def describe(self) -> str:
        return f"{self.seat.name} is asked: {self.question}"

    def request(self, game: GameState) -> DecisionRequest:
        return Confirm(
            seat=self.seat,
            candidates=self.subjects,
            question=self.question,
            resolver=self.resolver,
            source_id=self.source_id,
            declinable=self.declinable,
        )


@dataclass(frozen=True, slots=True)
class Choose(InterruptingEffect):
    """Pause the cascade so ``seat`` picks between ``minimum`` and ``maximum`` of ``candidates``.
    The chosen ids feed the registered ``resolver``, whose effects apply on resume.

    Attributes
    ----------
    seat : PlayerId
        The seat that chooses.
    candidates : tuple of str
        The card ids the seat may pick among.
    minimum : int
        The fewest cards the seat may pick. Zero when the choice is optional.
    maximum : int
        The most cards the seat may pick.
    resolver : str
        The registered choice resolver naming what the chosen ids do.
    source_id : str, optional
        A card id handed to the resolver as its context. Which card that is belongs to the resolver.
        Often the one whose trigger raised the choice, sometimes the card being acted on. None when
        the rulebook raises the choice and there is no card to name. Default None.
    resolver_context : tuple of str, optional
        What an earlier step of the same choice settled, handed to the resolver alongside the chosen
        ids. A card that asks two questions in a row carries what the first one answered here,
        rather than reading it back off the game. Default empty.
    declinable : bool, optional
        Whether choosing nothing is an answer as well as a count within the bounds, as "may target
        and move home exactly two units" reads. Default False.
    limits : tuple of :class:`~.PickLimit`, optional
        What the cards picked together must satisfy beyond their number. Default none.
    options : tuple of str, optional
        Named answers offered beside the cards, for a text whose alternative is not on the board.
        Default none.
    """

    seat: PlayerId
    candidates: tuple[str, ...]
    minimum: int
    maximum: int
    resolver: str
    source_id: str | None = None
    resolver_context: tuple[str, ...] = ()
    declinable: bool = False
    limits: tuple[PickLimit, ...] = ()
    options: tuple[str, ...] = ()

    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        """A cost that asks the seat to pick cannot be met where no answer its limits allow
        exists. An option is an answer of its own, so one on offer is enough."""
        return bool(self.options) or answerable(self.candidates, self.minimum, self.limits)

    def describe(self) -> str:
        return (
            f"{self.seat.name} chooses {self.minimum}-{self.maximum} of "
            f"{len(self.candidates)} for {self.resolver}"
        )

    def request(self, game: GameState) -> DecisionRequest:
        return ChooseCards(
            seat=self.seat,
            candidates=self.candidates,
            minimum=self.minimum,
            maximum=self.maximum,
            resolver=self.resolver,
            source_id=self.source_id,
            resolver_context=self.resolver_context,
            declinable=self.declinable,
            limits=self.limits,
            options=self.options,
        )


def _at_random(game: GameState, card_ids: tuple[str, ...], count: int) -> tuple[str, ...]:
    """``count`` of ``card_ids`` picked from the game's own stream, in their given order, or all of
    them when there are no more than ``count``."""
    if len(card_ids) <= count:
        return card_ids
    picked = game.rng.choice(len(card_ids), size=count, replace=False)
    return tuple(card_ids[index] for index in sorted(picked))


@dataclass(frozen=True, slots=True)
class DiscardFromHand(InterruptingEffect):
    """``holder`` discards ``count`` cards from hand, chosen by ``picker`` or at random.

    "Must discard a card" and the maximum hand size make the holder the picker. A card that has its
    own seat choose from another player's hand names that seat, after a :class:`~.LookAtHand` so the
    seat can read the cards. "Discards a card at random" names no picker. The answer comes back as
    this effect with ``candidates`` narrowed to the cards chosen, which then discards them.

    Every card goes to the discard before any is announced, as one instant. Nothing is asked when
    there is nothing to choose: a random discard, or a hand no larger than ``count``, which is
    discarded whole.

    Attributes
    ----------
    holder : PlayerId
        The seat whose hand the cards leave.
    count : int
        How many cards are discarded.
    cause : PlayerId, Rulebook or Trait
        Who or what the discard belongs to, carried onto each ``CardDiscarded``.
    picker : PlayerId or None
        The seat that chooses the cards, or None for a discard at random.
    candidates : tuple of str, optional
        The cards eligible, for a card that limits them ("a copy of the named card"). Default
        None, for the whole hand as it stands when the discard resolves.
    """

    holder: PlayerId
    count: int
    cause: Cause
    picker: PlayerId | None
    candidates: tuple[str, ...] | None = None

    def describe(self) -> str:
        how = "at random" if self.picker is None else f"chosen by {self.picker.name}"
        return f"{self.holder.name} discards {self.count} from hand, {how}"

    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        """A cost of discarding cards cannot be met with too few to discard."""
        return len(self._eligible(game)) >= self.count

    def pauses(self, game: GameState) -> bool:
        return self.picker is not None and len(self._eligible(game)) > self.count

    def is_negatable(self, game: GameState) -> bool:
        return True

    def would_happen(self, game: GameState) -> bool:
        """Whether any card would leave the hand."""
        return self.count > 0 and bool(self._eligible(game))

    def request(self, game: GameState) -> DecisionRequest:
        if self.picker is None:
            raise RuntimeError("a random discard asks no one")
        return ChooseDiscard(
            seat=self.picker,
            candidates=self._eligible(game),
            count=self.count,
            holder=self.holder,
            cause=self.cause,
        )

    def perform(self, game: GameState) -> list[GameEvent]:
        by_id = game.table.cards_by_id
        discarded = [
            by_id[card_id] for card_id in _at_random(game, self._eligible(game), self.count)
        ]
        for card in discarded:
            ops.move_card(game.table, card, pile_for(card))
        return [
            CardDiscarded(card.id, card.side, self.cause, CardLocation.HAND) for card in discarded
        ]

    def _eligible(self, game: GameState) -> tuple[str, ...]:
        """The candidates still in the holder's hand, or the whole hand when none are named."""
        hand = tuple(card.id for card in cards_in_hand(game, self.holder))
        if self.candidates is None:
            return hand
        return tuple(card_id for card_id in self.candidates if card_id in hand)


@dataclass(frozen=True, slots=True)
class ReshuffleFromHand(Effect):
    """``holder`` shuffles ``count`` cards picked at random from their hand into their Fate deck,
    or their whole hand when it holds no more than ``count``.

    Attributes
    ----------
    holder : PlayerId
        The seat whose hand and Fate deck they are.
    count : int
        How many cards are reshuffled.
    """

    holder: PlayerId
    count: int

    def describe(self) -> str:
        return f"{self.holder.name} reshuffles {self.count} from hand at random"

    def perform(self, game: GameState) -> list[GameEvent]:
        deck = DeckKey(self.holder, Side.FATE)
        hand = tuple(card.id for card in cards_in_hand(game, self.holder))
        for card_id in _at_random(game, hand, self.count):
            ops.move_card(game.table, game.table.cards_by_id[card_id], deck)
        game.table.decks[deck].shuffle(game.rng)
        return []


@dataclass(frozen=True, slots=True)
class Arrange(InterruptingEffect):
    """Pause the cascade so ``seat`` puts ``candidates`` in an order, then hand the order to a
    resolver. The answer's contract is :class:`~.ArrangeCards`'s.

    Attributes
    ----------
    seat : PlayerId
        The seat arranging.
    candidates : tuple of str
        The card ids to order.
    resolver : str
        The registered choice resolver naming what the order does.
    source_id : str or None
        A card id handed to the resolver as its context, or None.
    to_bottom : bool, optional
        Whether the cards are going to the bottom of a deck rather than the top. Default False.
    """

    seat: PlayerId
    candidates: tuple[str, ...]
    resolver: str
    source_id: str | None
    to_bottom: bool = False

    def pauses(self, game: GameState) -> bool:
        """Nothing to arrange is nothing to ask: the cascade walks past an empty arrangement."""
        return bool(self.candidates)

    def perform(self, game: GameState) -> list[GameEvent]:
        return []

    def describe(self) -> str:
        end = "the bottom" if self.to_bottom else "the top"
        return f"{self.seat.name} orders {len(self.candidates)} for {end} for {self.resolver}"

    def request(self, game: GameState) -> DecisionRequest:
        return ArrangeCards(
            seat=self.seat,
            candidates=self.candidates,
            resolver=self.resolver,
            source_id=self.source_id,
            to_bottom=self.to_bottom,
        )


@dataclass(frozen=True, slots=True)
class AskDistribution(InterruptingEffect):
    """Pause the cascade so ``seat`` divides ``count`` creations among ``candidates``, then hand the
    division to a resolver.

    For the "attach them to one or more of your Personalities" a card leaves to its controller: how
    many go where is the whole of the choice, so the resolver reads the answer as a tally rather
    than as a set. A candidate named twice takes two.

    Attributes
    ----------
    seat : PlayerId
        The seat dividing them.
    candidates : tuple of str
        The card ids the creations may be divided among.
    count : int
        How many there are to divide.
    resolver : str
        The registered choice resolver naming what the division does.
    source_id : str
        The card dividing them.
    """

    seat: PlayerId
    candidates: tuple[str, ...]
    count: int
    resolver: str
    source_id: str

    def describe(self) -> str:
        return f"{self.seat.name} divides {self.count} among {len(self.candidates)} for {self.resolver}"

    def request(self, game: GameState) -> DecisionRequest:
        """Raise ValueError if there is nothing to divide or nowhere to put it. The cascade pauses
        on every interrupting effect, so a caller that asks either way would stop the game on a
        question its seat can never finish answering."""
        if not self.count or not self.candidates:
            raise ValueError(
                f"{self.source_id} cannot divide {self.count} among {len(self.candidates)} cards"
            )
        return ChooseDistribution(
            seat=self.seat,
            candidates=self.candidates,
            count=self.count,
            resolver=self.resolver,
            source_id=self.source_id,
        )

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import ClassVar

from yasuki_core.engine import ops
from yasuki_core.engine.registrar import FlagRegistry
from yasuki_core.engine.rules.battle.presence import place_unit
from yasuki_core.engine.rules.rulebook import favor_proxy
from yasuki_core.engine.rules.rulebook.copies import copy_may_enter
from yasuki_core.engine.players import Cause, PlayerId
from yasuki_core.engine.rules.units.membership import unit_of
from yasuki_core.engine.rules.stats.calculation import effective_stat
from yasuki_core.engine.rules.vocabulary.decisions import (
    ArrangeCards,
    ChooseAmount,
    ChooseCards,
    ChooseDistribution,
    ChooseOption,
    Confirm,
    DecisionRequest,
)
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.engine.rules.vocabulary.looks import Look
from yasuki_core.engine.rules.vocabulary.game_events import (
    CardDiscarded,
    CounterGained,
    Destroyed,
    Dishonored,
    EnteredPlay,
    FavorDiscarded,
    GameEvent,
    HonorChanged,
    Rehonored,
    Revealed,
    Straightened,
)
from yasuki_core.engine.rules.vocabulary.modifiers import (
    AbilityGrant,
    Condition,
    ConditionalModifier,
    Duration,
    KeywordGrant,
    LobbyModifier,
    Minimum,
    Modifier,
    ProvinceModifier,
    SeatAbilityGrant,
    Stat,
)
from yasuki_core.engine.rules.state import GameState, claim_once_per_turn, seat_once_key
from yasuki_core.engine.rules.turn.structure import END_OF_TURN, Moment, flow_resolves
from yasuki_core.engine.table import (
    BATTLEFIELD,
    UNPLACED_BOARD_POS,
    DeckKey,
    Location,
    ZoneKey,
    ZoneRole,
    location_of,
)
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import PersonalityPrint
from yasuki_core.game_pieces.counters import Counter


def _pile(card: L5RCard, *, banished: bool = False) -> ZoneKey:
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


class InterruptingEffect(Effect, ABC):
    """An effect that pauses the cascade to put a question to a seat.

    The walker records :meth:`request` as the pending decision and stashes the rest of the cascade,
    resuming once the seat answers. It calls :meth:`~.perform` only on one whose :meth:`pauses`
    says there is no one to ask.
    """

    __slots__ = ()

    @abstractmethod
    def request(self, game: GameState) -> DecisionRequest:
        """The decision to put to the seat."""

    def is_interruptible(self, game: GameState) -> bool:
        """False: a question the action asks is nothing to interrupt, and what its answer produces
        is not known until it is answered, so neither is offered at the Interrupt step."""
        return False

    def pauses(self, game: GameState) -> bool:
        """Whether the cascade stops here. True unless a subclass finds nobody to answer, in which
        case the walker performs the effect instead of asking."""
        return True

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

    def describe(self) -> str:
        return f"negated: {self.effect.describe()}"

    def narrate(self, game: GameState) -> str:
        return f"negated: {self.effect.narrate(game)}"


@dataclass(frozen=True, slots=True)
class AdjustCounter(Effect):
    """Add ``delta`` to a counter on a card (floored at zero by the card). A grant is a positive
    delta, a removal negative. The rules-side twin of the sandbox ``AdjustCounter`` intent, applied
    through :meth:`Effect.perform` rather than ``apply_intent``."""

    card_id: str
    counter: Counter
    delta: int

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
        gained = card.counters.get(self.counter.key, 0) - before
        if gained > 0:
            return [CounterGained(self.card_id, self.counter, gained)]
        return []


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

    def describe(self) -> str:
        return f"{self.card_id} to {self.seat.name}'s hand"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is not None:
            ops.move_card(game.table, card, ZoneKey(self.seat, ZoneRole.HAND))
        return []


def _remove_unit(game: GameState, card: L5RCard, *, banished: bool = False) -> tuple[L5RCard, ...]:
    """Send ``card`` and everything attached to him out of play, to their discards or to their
    banishes when ``banished``. Return the unit that left so the caller can announce each
    departure in its own words (CR, Unit).

    A created card among them has no pile of either kind and is taken off the table instead, which
    the move itself sees to (CR, Create). It still announces its departure, because a card reacting
    to a Follower being destroyed does not care where the Follower came from.
    """
    unit = unit_of(game, card)
    for member in unit:
        ops.move_card(game.table, member, _pile(member, banished=banished))
    return unit


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
    """

    card_id: str
    cause: Cause

    def describe(self) -> str:
        return f"destroy {self.card_id}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None:
            return []
        location = location_of(game.table, card)
        return [
            Destroyed(member.id, self.cause, location, controller=member.owner)
            for member in _remove_unit(game, card)
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

    def describe(self) -> str:
        return f"{self.cause.name} discards {self.card_id}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None:
            return []
        unit = _remove_unit(game, card)
        return [CardDiscarded(member.id, member.side, self.cause) for member in unit]


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

    def describe(self) -> str:
        return f"banish {self.card_id}"

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
    until : Moment
        The boundary of play it waits for. Resolving a delay to a moment the flow never reaches
        raises ``ValueError`` rather than holding the effect for the rest of the game.
    """

    effect: Effect
    until: Moment

    def describe(self) -> str:
        return f"{self.effect.describe()} {self.until.describe()}"

    def perform(self, game: GameState) -> list[GameEvent]:
        if not flow_resolves(self.until):
            raise ValueError(f"nothing resolves {self.until.describe()}")
        game.delayed.append((self.until, self.effect))
        return []


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
    """Destroy ``seat``'s Province ``zone``: its contents go to the discard face-up and the Province
    itself leaves the board. A Province already gone is a no-op.

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

    def perform(self, game: GameState) -> list[GameEvent]:
        if self.zone not in game.table.zones:
            return []
        moved = ops.destroy_province(game.table, self.seat, self.zone)
        cards = game.table.cards_by_id
        return [CardDiscarded(card_id, cards[card_id].side, self.seat) for card_id in moved]


@dataclass(frozen=True, slots=True)
class PlaceInProvince(Effect):
    """Put a card into a Province face-up. A no-op when the card is gone or the Province is full."""

    card_id: str
    zone: ZoneKey

    def describe(self) -> str:
        return f"place {self.card_id} in {self.zone.owner.name} province {self.zone.idx}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        province = game.table.zones.get(self.zone)
        if card is None or province is None or not province.has_capacity():
            return []
        ops.move_card(game.table, card, self.zone)
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


@dataclass(frozen=True, slots=True)
class GrantModifier(Effect):
    """Record a continuous stat modifier: the ``source`` card grants ``target`` a change of
    ``amount`` to ``stat`` for ``duration``. The single created-effect entry point. A card's
    counters and attachments grant their bonuses without one (they are derived on read)."""

    source_id: str
    target_id: str
    stat: Stat
    amount: int
    duration: Duration

    def describe(self) -> str:
        return (
            f"{self.source_id} grants {self.target_id} {self.amount:+d} "
            f"{self.stat.name} ({self.duration.name})"
        )

    def perform(self, game: GameState) -> list[GameEvent]:
        game.ongoing.append(
            Modifier(self.source_id, self.target_id, self.stat, self.amount, self.duration)
        )
        return []


@dataclass(frozen=True, slots=True)
class GrantConditionalModifier(Effect):
    """Record a continuous stat modifier on every card meeting ``condition``: the ``source`` card
    grants a change of ``amount`` to ``stat`` for ``duration`` to whichever cards satisfy it at
    each read. The conditional counterpart of :class:`~.GrantModifier`."""

    source_id: str
    condition: Condition
    stat: Stat
    amount: int
    duration: Duration

    def describe(self) -> str:
        return (
            f"{self.source_id} grants {self.amount:+d} {self.stat.name} while "
            f"{self.condition.value} ({self.duration.name})"
        )

    def perform(self, game: GameState) -> list[GameEvent]:
        game.ongoing.append(
            ConditionalModifier(
                self.source_id, self.condition, self.stat, self.amount, self.duration
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
    duration: Duration

    def describe(self) -> str:
        return f"{self.source_id} grants {self.target_id} an ability ({self.duration.name})"

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
    duration: Duration

    def describe(self) -> str:
        return f"{self.source_id} grants {self.seat.name}'s cards an ability ({self.duration.name})"

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
    duration: Duration

    def describe(self) -> str:
        return (
            f"{self.source_id} gives {self.target_id} a minimum {self.stat.name} of {self.value} "
            f"({self.duration.name})"
        )

    def perform(self, game: GameState) -> list[GameEvent]:
        game.ongoing.append(
            Minimum(self.source_id, self.target_id, self.stat, self.value, self.duration)
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
    duration: Duration

    def describe(self) -> str:
        return (
            f"{self.source_id} gives {self.province.token} {self.amount:+d} province strength "
            f"({self.duration.name})"
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
class PayFavorCost(Effect):
    """Record that the action now resolving is paying a Favor cost.

    Carried by the cost itself rather than set when the action is announced, so an action offering
    the Favor as one of two ways to pay counts as a Favor action only on the branch that takes it
    (ShE datasheet, The Favor Icon).
    """

    def describe(self) -> str:
        return "the action pays a Favor cost"

    def perform(self, game: GameState) -> list[GameEvent]:
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
    duration: Duration

    def describe(self) -> str:
        return (
            f"{self.source_id} gives {self.seat.name} a {self.amount:+d} Lobby Bonus "
            f"({self.duration.name})"
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
    """

    # What the card prints this effect as, which is the only thing its description needs from the
    # subclass. Abstract, so the category cannot be announced on its own, and a class attribute on
    # each kind rather than a field: it belongs to the kind, not to one announcement.
    @property
    @abstractmethod
    def name(self) -> str: ...

    strength: int
    target_id: str
    cause: Cause
    compared: Stat = Stat.FORCE
    outcome: tuple[Effect, ...] = ()

    def __post_init__(self) -> None:
        if not self.outcome:
            object.__setattr__(self, "outcome", self._printed_outcome())

    @abstractmethod
    def _printed_outcome(self) -> tuple[Effect, ...]:
        """What this kind does to a target its strength reaches, as the CR prints it."""

    def describe(self) -> str:
        return f"{self.name} {self.strength} on {self.target_id}{self._compared_stat()}"

    def _compared_stat(self) -> str:
        return "" if self.compared is Stat.FORCE else f" vs {self.compared.name}"

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
        target = game.table.cards_by_id[self.target_id].name
        return f"{self.name.capitalize()} {self.strength} on {target}{self._compared_stat()}"

    def _printed_outcome(self) -> tuple[Effect, ...]:
        return (Bow(self.target_id),)


@dataclass(frozen=True, slots=True)
class StartDuel(Effect):
    """Have ``challenger`` challenge ``challenged`` to a duel, and open its focusing.

    The seats are the two Personalities' own, so a card creating a duel names the duelists and
    nothing else.

    Attributes
    ----------
    challenger : str
        The id of the Personality issuing the challenge.
    challenged : str
        The id of the Personality challenged, whose seat has the first option to focus or strike.
    source_card_id : str
        The id of the card creating the duel, which the duel records so a consequence can name what
        set it.
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

        challenger = game.table.cards_by_id[self.challenger]
        challenged = game.table.cards_by_id[self.challenged]
        declare_duel(
            game,
            challenger=challenger.owner,
            challenged=challenged.owner,
            challenger_duelist=challenger.id,
            challenged_duelist=challenged.id,
            source=self.source_card_id,
        )
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
        from yasuki_core.engine.rules.duel.procedure import current_duel
        from yasuki_core.engine.rules.duel.records import DuelStep
        from yasuki_core.engine.rules.duel.resolution import end_without_resolution

        duel = current_duel(game)
        if duel is None or duel.step is DuelStep.ENDED:
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
        game.round = replace(game.round, priority=self.seat, passes=0)
        return []


@dataclass(frozen=True, slots=True)
class AdditionalAction(Effect):
    """Grant ``seat`` an additional action: once the action now resolving is done, the opportunity
    to act stays with ``seat`` instead of passing on (CR, Additional Action). A pass taken at that
    opportunity does not count toward closing the round."""

    seat: PlayerId

    def describe(self) -> str:
        return f"{self.seat.name} takes an additional action"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.additional_action = self.seat
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
    duration: Duration

    def describe(self) -> str:
        return f"{self.source_id} gives {self.target_id} {self.keyword} ({self.duration.name})"

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
    moves units. One elsewhere arrives on the battlefield first.

    Attributes
    ----------
    card_id : str
        The card to attach.
    target_id : str
        The Personality it attaches to.
    """

    card_id: str
    target_id: str

    def describe(self) -> str:
        return f"attach {self.card_id} to {self.target_id}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        personality = game.table.cards_by_id.get(self.target_id)
        if card is None or personality is None:
            return []
        entering = not any(held is card for held in game.table.battlefield.cards)
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
    """

    card_id: str
    battlefield: int | None = None

    def describe(self) -> str:
        if self.battlefield is not None:
            return f"put {self.card_id} into play at battlefield {self.battlefield}"
        return f"put {self.card_id} into play"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None or any(held is card for held in game.table.battlefield.cards):
            return []
        if not copy_may_enter(game, card.owner, card):
            return []
        hand = game.table.zones[ZoneKey(card.owner, ZoneRole.HAND)]
        from_hand = any(held is card for held in hand.cards)
        ops.move_card(game.table, card, BATTLEFIELD, position=UNPLACED_BOARD_POS)
        # Not through place_unit: a Terrain is no unit, and the presence record it keeps is of
        # units alone.
        if self.battlefield is not None:
            assert game.attack is not None and 0 <= self.battlefield < len(game.attack.battlefields)
            ops.set_location(game.table, card, Location.at_battlefield(self.battlefield))
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
    """

    token_id: str
    owner: PlayerId
    creator_id: str
    attach_to: str | None = None
    stats: tuple[tuple[Stat, int], ...] = ()
    clan: str | None = None
    banish_at_turn_end: bool = False

    def describe(self) -> str:
        fixed = [self.clan] if self.clan else []
        fixed += [f"{stat.name} {value}" for stat, value in self.stats]
        where = "" if self.attach_to is None else f" on {self.attach_to}"
        given = f" with {', '.join(fixed)}" if fixed else ""
        return f"{self.owner.name} creates {self.token_id}{where}{given}"

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
        card = ops.spawn_token(
            game.table, game.mint_token_id(), printed, self.owner, position=UNPLACED_BOARD_POS
        )
        game.created_by[card.id] = self.creator_id
        if self.banish_at_turn_end:
            game.delayed.append((END_OF_TURN, Banish(card.id)))
        if personality is not None:
            ops.attach_to_personality(game.table, card, personality)
        return [EnteredPlay(card.id, from_hand=False)]


@dataclass(frozen=True, slots=True)
class PayGold(InterruptingEffect):
    """Pay gold, bowing producers to raise what the seat's pool does not already cover.

    The cost a card charges in Gold, as opposed to the Gold a Recruit charges for the card itself:
    both raise the same payment, and this one carries no card being paid for. It pauses the cascade
    for the seat to pick which producers to bow, so it resolves before whatever an ability's text
    sequences behind it.

    Attributes
    ----------
    seat : PlayerId
        The seat being charged.
    amount : int
        The gold to raise.
    label : str
        What the payment is for, shown in the prompt.
    """

    seat: PlayerId
    amount: int
    label: str

    def describe(self) -> str:
        return f"{self.seat.name} pays {self.amount} gold for {self.label}"

    # Imported where they are used: pricing a payment reads the production-boost registry, whose
    # module imports this one.
    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        from yasuki_core.engine.rules.gold.payment import can_afford

        return can_afford(game, self.seat, self.amount, bowed_by_cost=bowed_by_cost)

    def request(self, game: GameState) -> DecisionRequest:
        from yasuki_core.engine.rules.gold.payment import payment_request

        return payment_request(game, self.seat, self.amount, self.label)


@dataclass(frozen=True, slots=True)
class AskAmount(InterruptingEffect):
    """Pause for the seat to say how much Gold it spends on a variable cost, then hand the amount to
    a resolver.

    The ``:X:`` in a cost block: the amount is settled during the Pay Costs step and everything the
    action does is shaped by it (CR, Action Sequence, Good Faith). The seat declares the amount, the
    engine charges it less ``discount``, and the resolver reads the amount declared.

    Attributes
    ----------
    seat : PlayerId
        The seat choosing and paying.
    amounts : tuple of int
        The amounts on offer, which the caller narrows to what the seat can declare and what would
        leave the action something legal to do. Pricing the cost narrows them to what the seat can
        pay.
    question : str
        What the amount is for, as the seat reads it.
    resolver : str
        The registered choice resolver the chosen amount is handed to.
    source_id : str
        The card charging the cost.
    discount : int, optional
        The Gold the action's discount takes off the declared amount: what is left of it once the
        cost's fixed Gold has taken its share. Default 0.
    """

    seat: PlayerId
    amounts: tuple[int, ...]
    question: str
    resolver: str
    source_id: str
    discount: int = 0

    def describe(self) -> str:
        return f"{self.seat.name} is asked: {self.question}"

    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        """Nothing to choose from is nothing to pay."""
        return bool(self.amounts)

    def request(self, game: GameState) -> DecisionRequest:
        return ChooseAmount(
            seat=self.seat,
            candidates=tuple(str(amount) for amount in self.amounts),
            question=self.question,
            resolver=self.resolver,
            source_id=self.source_id,
            discount=self.discount,
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
    """

    seat: PlayerId
    options: tuple[str, ...]
    question: str
    resolver: str
    source_id: str
    resolver_context: tuple[str, ...] = ()

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
        )


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
    """Bow a card."""

    card_id: str

    def describe(self) -> str:
        return f"bow {self.card_id}"

    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        """An already-bowed card cannot bow again."""
        card = game.table.cards_by_id.get(self.card_id)
        return card is not None and not card.bowed

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is not None:
            card.bow()
        return []


@dataclass(frozen=True, slots=True)
class Straighten(Effect):
    """Straighten (unbow) a card. Announces the change, which a card that watches for its own
    straightening reads. One already standing, or forbidden to straighten, announces nothing."""

    card_id: str

    def describe(self) -> str:
        return f"straighten {self.card_id}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None or not card.bowed or self.card_id in game.straighten_delayed:
            return []
        card.unbow()
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
    reacts to a rehonoring reads. One already honorable announces nothing."""

    card_id: str

    def describe(self) -> str:
        return f"rehonor {self.card_id}"

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
    and the destruction is deferred through ``Then`` so the Personality's own reaction to his
    rehonoring fires while he is still in play. The CR adds that neither can be negated, which
    nothing here models because negation is not modeled.

    Parameters
    ----------
    card_id : str
        The Personality committing seppuku.
    cause : PlayerId, Rulebook or Trait
        Who or what directed it: the seat whose card did, or the rule that demanded it.
    """
    return [Rehonor(card_id), Then((Destroy(card_id, cause),))]


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
            card.add_peeker(self.seat)
        game.look = Look(self.seat, self.deck, tuple(card.id for card in seen))
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
                ops.move_card(game.table, card, self.deck, to_bottom=self.to_bottom)
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
        ops.move_card(game.table, card, self.deck, deck_index=index)
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


# Cards whose controller does not lose Honor from their own cards' effects, keyed on printed id. A
# rulebook loss, such as a dishonorable Personality's destruction, is no card's effect and still
# lands (CR, Dishonorable).
HONOR_LOSS_SHIELDS = FlagRegistry("honor loss shields", "already shields its controller's Honor")
register_honor_loss_shield = HONOR_LOSS_SHIELDS.make_register()


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
        The card whose effect this is, so a shield against a seat's own cards' losses can tell
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
        if self.amount < 0 and self._shielded(game):
            return False
        return self.amount != 0

    def perform(self, game: GameState) -> list[GameEvent]:
        amount = self.adjusted
        if amount < 0 and self._shielded(game):
            return []
        rehonored = self._substituted_for(game) if amount > 0 else []
        if rehonored:
            for card in rehonored:
                card.rehonor()
            return [Rehonored(card.id) for card in rehonored]
        if not ops.set_honor(game.table, self.seat, delta=amount):
            return []
        return [HonorChanged(self.seat, amount)]

    def _shielded(self, game: GameState) -> bool:
        """Whether the loss comes from a card ``seat`` controls while ``seat`` controls a card
        that says it does not lose Honor from its own cards' effects."""
        source = game.table.cards_by_id.get(self.source_id) if self.source_id else None
        if source is None or source.owner is not self.seat:
            return False
        return any(
            card.owner is self.seat and card.printed_id in HONOR_LOSS_SHIELDS
            for card in game.table.battlefield.cards
        )

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
class DelayStraighten(Effect):
    """Forbid ``card_id`` from straightening until its controller's next Action Phase has ended.

    Blocks any attempt to straighten the card while it holds, not just the turn-start straighten.
    Imposed, unlike the printed "May remain bowed" its controller chooses each turn."""

    card_id: str

    def describe(self) -> str:
        return f"{self.card_id} may not straighten until after its next Action Phase"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.straighten_delayed[self.card_id] = game.turn
        return []


@dataclass(frozen=True, slots=True)
class IgnoreHonorRequirements(Effect):
    """Grant ``seat`` the standing waiver of every Personality's Honor Requirement when
    recruiting."""

    seat: PlayerId

    def describe(self) -> str:
        return f"{self.seat.name} ignores honor requirements"

    def perform(self, game: GameState) -> list[GameEvent]:
        ops.set_ignore_honor_requirements(game.table, self.seat, True)
        return []


@dataclass(frozen=True, slots=True)
class RecruitCard(InterruptingEffect):
    """Bring a card into play from its controller's province, out of the normal recruit sequence.

    Pauses for the payment its controller must cover, exactly as a Recruit action does. With
    ``renew`` the vacated province refills face-up on top of whatever the card's own Renew keyword
    grants.
    """

    card_id: str
    renew: bool = False

    def describe(self) -> str:
        renewed = ", renewing the province" if self.renew else ""
        return f"recruit {self.card_id} out of sequence{renewed}"

    def pauses(self, game: GameState) -> bool:
        """No payment is asked for a card Unique or Singular keeps out of play."""
        card = game.table.cards_by_id[self.card_id]
        return copy_may_enter(game, card.owner, card)

    def perform(self, game: GameState) -> list[GameEvent]:
        return []

    def request(self, game: GameState) -> DecisionRequest:
        # Announcing a recruit builds a payment, and the payment loop is written in the effects
        # this module defines -- so the entry point is reached lazily whatever module holds it.
        from yasuki_core.engine.rules.rulebook.recruit import announce_recruit

        card = game.table.cards_by_id[self.card_id]
        return announce_recruit(game, card, card.owner, invest_amount=None, renew=self.renew)


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
    """Resolve ``effects`` once the current step finishes. The generic deferral: an effect that must
    wait for what precedes it to resolve fully, including any cascade it raises, is queued here
    rather than placed inline, where it would run ahead of the events already in flight.

    Attributes
    ----------
    effects : tuple of Effect
        The effects to resolve, in order.
    interruptible : bool, optional
        Whether the effects are an action's own, open to the Interrupt step. Default False.
    triggered : bool, optional
        Whether the effects are a trigger's, so a decision among them is the trigger's question and
        cannot be backed out of. Default False.
    """

    effects: tuple[Effect, ...]
    interruptible: bool = False
    triggered: bool = False

    def resume(self, game: GameState) -> None:
        # The cascade imports this module, so the one module this item drives cannot be imported at
        # the top without closing that cycle.
        from yasuki_core.engine.rules import triggers

        if self.interruptible:
            triggers.resolve_action_effects(game, list(self.effects))
        else:
            triggers.resolve_effects(game, list(self.effects), triggered=self.triggered)


@dataclass(frozen=True, slots=True)
class Then(Effect):
    """Defer ``effects`` until the current step has fully resolved, cascade included.

    Effects placed inline run before the events already queued behind them, so a step that must
    follow another card's reaction to what just happened belongs here instead.
    """

    effects: tuple[Effect, ...]

    def describe(self) -> str:
        return f"then: {len(self.effects)} deferred"

    def perform(self, game: GameState) -> list[GameEvent]:
        """Defer the effects with no Interrupt step open on them. The cascade handles a ``Then``
        itself, carrying the provenance of the effects around it, so this runs only when a ``Then``
        is applied outside the cascade."""
        game.stack.append(ApplyEffects(self.effects))
        return []


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
    """

    seat: PlayerId
    candidates: tuple[str, ...]
    minimum: int
    maximum: int
    resolver: str
    source_id: str | None = None

    def is_payable(self, game: GameState, *, bowed_by_cost: frozenset[str] = frozenset()) -> bool:
        """A cost that asks the seat to pick cannot be met with too few to pick from."""
        return len(self.candidates) >= self.minimum

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
        )


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

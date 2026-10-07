import collections
from typing import NamedTuple
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.game_events import (
    ActionResolved,
    CardDiscarded,
    ConditionFulfilled,
    Destroyed,
    Destroying,
    EnteredPlay,
    GameEvent,
    NextTime,
    names_both_edges,
    opens_a_window,
)
from yasuki_core.engine.rules.vocabulary.decisions import (
    CHOICE_PICKS,
    CHOICE_PROMPTS,
    ChooseNextTrigger,
)
from yasuki_core.engine.rules.effects import (
    ApplyEffects,
    DelayedEffect,
    Attributed,
    InterruptingEffect,
    Effect,
    Negated,
    Simultaneously,
    To,
)
from yasuki_core.engine.rules import state_based_actions
from yasuki_core.engine.rules.negation import negate_committed, spend_once, would_negate
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.structure import END_OF_TURN, STEP_ROUNDS, Moment
from yasuki_core.engine.rules.stats.ongoing_grants import grant_applies
from yasuki_core.engine.rules.vocabulary.modifiers import (
    AbilityGrant,
    CompassionGrant,
    ConditionalModifier,
    Duration,
    Lifetime,
    LobbyModifier,
    Negation,
    Ongoing,
    ProvinceModifier,
    SeatAbilityGrant,
)
from yasuki_core.engine.rules.vocabulary.locations import CardLocation
from yasuki_core.engine.rules.vocabulary.segments import Boundary
from yasuki_core.engine.rules.vocabulary.work import Provenance
from yasuki_core.ruleset import in_force
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import Counter
from yasuki_core.game_pieces.text_split import split_text_box

# A sanity bound on both fixpoint walks: a converging cascade drains in a handful of events, and
# the state-based actions settle in a handful of rounds, so far more than this means a trigger
# re-emits an event that re-fires it or a rule demands what does not satisfy it: a bug, raised
# loudly.
_MAX_CASCADE = 1000

# The tail of the current walk, kept only to describe a cascade that fails to converge. Module-level
# and bounded rather than carried on GameState: the history is derived (replay regenerates it), and
# GameState compares by field, so storing it there would drag traces into every replay-equality
# assertion. A deque of this size holds several cycles of any loop a human would need to read.
_TRACE_LIMIT = 60
_trace: collections.deque[str] = collections.deque(maxlen=_TRACE_LIMIT)


@dataclass(frozen=True, slots=True)
class TriggerContext:
    """What a trigger reads: the live game, the card whose trigger is firing, and the event. A
    rulebook trigger has no card of its own and reads the card the event names instead."""

    game: GameState
    card: L5RCard
    event: GameEvent


Trigger = Callable[[TriggerContext], list[Effect]]


class Registration(NamedTuple):
    """A trigger as registered.

    Attributes
    ----------
    trigger : callable
        What runs when the event fires.
    ruleset : str or None
        The one ruleset the trigger is read under, or None for every arc.
    boundary : Boundary or None
        The edge of its own step the trigger answers, for an event announced at each of them. None
        for an event with one firing.
    """

    trigger: Trigger
    ruleset: str | None
    boundary: Boundary | None = None


# How a client names a trigger waiting to fire: maps (game, the card it fires on) to its label.
TriggerLabel = Callable[[GameState, L5RCard], str]


def printed_trait(game: GameState, card: L5RCard) -> str:
    """``card``'s printed trait when it prints exactly one, and otherwise "<name>'s triggered
    ability"."""
    traits = split_text_box(card.active_face.text).traits
    return traits[0] if len(traits) == 1 else f"{card.name}'s triggered ability"


def trait_opening(prefix: str) -> TriggerLabel:
    """A label reading the printed trait that opens with ``prefix``, as "Yu:" or "Invest"."""

    def label(game: GameState, card: L5RCard) -> str:
        traits = split_text_box(card.active_face.text).traits
        return next(
            (trait for trait in traits if trait.startswith(prefix)), printed_trait(game, card)
        )

    return label


# trigger -> how the active player is told its name. Filled as triggers are registered.
_LABELS: dict[Trigger, TriggerLabel] = {}


def trigger_label(game: GameState, card: L5RCard, trigger: Trigger) -> str:
    """``trigger``'s name for the active player as it fires on ``card``: its registered label, or
    the card's printed trait."""
    return _LABELS.get(trigger, printed_trait)(game, card)


# event type -> where the card must be -> printed id -> its registrations. Populated by the @on
# decorators below, on import, and grouped by printed id so collection is a lookup rather than a
# rebuild per event. A zone nothing registers for is never walked, so a hand is read only for an
# event some card in hand answers.
_TRIGGERS: dict[type, dict[CardLocation, dict[str, list[Registration]]]] = {}


def on(
    event_type: type,
    printed_id: str,
    *,
    where: tuple[CardLocation, ...] = (CardLocation.BATTLEFIELD,),
    ruleset: str | None = None,
    boundary: Boundary | None = None,
    label: TriggerLabel = printed_trait,
) -> Callable[[Trigger], Trigger]:
    """Register the decorated function as ``printed_id``'s trigger for ``event_type``.

    Parameters
    ----------
    event_type : type
        The event the trigger answers.
    printed_id : str
        The card's printed id.
    where : tuple of :class:`~yasuki_core.engine.rules.vocabulary.locations.CardLocation`, optional
        Where the card must be for the trigger to fire. A card in hand answers only when its
        registration says so, as a Ring whose text reads "Play after X" does. Default the
        battlefield alone.
    ruleset : str, optional
        The name of the one ruleset the trigger is in force under, for a card whose text differs
        between arcs. Default None, for a text every arc reads.
    boundary : :class:`~yasuki_core.engine.rules.vocabulary.segments.Boundary`, optional
        Which edge of its own step the trigger answers. Required for an event announced at both
        edges, and refused for an event announced once.
    label : callable, optional
        Maps ``(game, card)`` to the trigger's name for the active player. Default the card's
        printed trait.

    Raises
    ------
    ValueError
        If ``event_type`` is announced at both edges of its step and no ``boundary`` names which one
        the trigger answers, or if it is announced once and a ``boundary`` is given anyway.
    """

    if event_type is ConditionFulfilled:
        raise ValueError("a watched condition is answered by its own watch; register one instead")
    if names_both_edges(event_type) and boundary is None:
        raise ValueError(f"{event_type.__name__} fires at both edges; name the boundary answered")
    if boundary is not None and not names_both_edges(event_type):
        raise ValueError(f"{event_type.__name__} fires once and has no boundary to answer")

    def register(trigger: Trigger) -> Trigger:
        _LABELS[trigger] = label
        by_zone = _TRIGGERS.setdefault(event_type, {})
        registered = Registration(trigger, ruleset, boundary)
        for location in where:
            by_zone.setdefault(location, {}).setdefault(printed_id, []).append(registered)
        return trigger

    return register


# Whether a granting card's text reaches a card: maps (game, granting card, card) to whether the
# card has the trigger the text gives right now.
Reach = Callable[[GameState, L5RCard, L5RCard], bool]


def given_by_effect(game: GameState, source: L5RCard, card: L5RCard) -> bool:
    """Whether an effect of ``source`` has given ``card`` its trigger, as "give a target
    Personality, 'Yu: ...'" does: a :class:`~.AbilityGrant` from ``source`` naming ``card``, still
    in force. The grant outlasts its source, so a Strategy discarded once it resolved still gives
    the trigger."""
    return any(
        isinstance(recorded, AbilityGrant)
        and recorded.source_id == source.id
        and recorded.target_id == card.id
        and grant_applies(game, recorded)
        for recorded in game.ongoing
    )


class GrantedTrigger(NamedTuple):
    """A trigger one card gives others, as registered: "Your Followers at this battlefield have,
    'Yu: ...'".

    Attributes
    ----------
    reaches : callable
        Maps ``(game, granting card, card)`` to whether the grant gives ``card`` the trigger now.
    trigger : callable
        What runs when the event fires, with the reached card as its context card.
    ruleset : str or None
        The one ruleset the grant is read under, or None for every arc.
    """

    reaches: Reach
    trigger: Trigger
    ruleset: str | None


# event type -> the granting card's printed id -> the triggers it gives. A granting card answers
# from the battlefield, and a granted trigger answers only events naming the card it is given.
_GRANTED_TRIGGERS: dict[type, dict[str, list[GrantedTrigger]]] = {}


def granted_trigger(
    event_type: type,
    printed_id: str,
    *,
    reaches: Reach,
    label: TriggerLabel,
    ruleset: str | None = None,
) -> Callable[[Trigger], Trigger]:
    """Register the decorated function as a trigger ``printed_id`` gives every card ``reaches``
    names while the granting card is in play, answering the events that name the reached card, as
    "Yu: ..." and "after this card is destroyed" do. The reached card fires it as its own trait, so
    the active player orders it among that card's triggers.

    Parameters
    ----------
    event_type : type
        The event the trigger answers.
    printed_id : str
        The granting card's printed id.
    reaches : callable
        Maps ``(game, granting card, card)`` to whether the grant gives ``card`` the trigger now.
    label : callable
        Maps ``(game, card)`` to the trigger's name for the active player.
    ruleset : str, optional
        The name of the one ruleset the grant is in force under. Default None, for every arc.
    """

    def register(trigger: Trigger) -> Trigger:
        _LABELS[trigger] = label
        granted = GrantedTrigger(reaches, trigger, ruleset)
        _GRANTED_TRIGGERS.setdefault(event_type, {}).setdefault(printed_id, []).append(granted)
        return trigger

    return register


# What a card watches the board for: "If X ever happens" and "Play if X" name a state, not an
# event.
WatchedCondition = Callable[[GameState, L5RCard], bool]


class Watch(NamedTuple):
    """A condition a card watches the board for, as registered.

    Attributes
    ----------
    key : str
        Names the watch among the card's others, so each is remembered and announced apart.
    condition : callable
        Maps ``(game, card)`` to whether the condition holds for that copy right now.
    reaction : callable
        The trigger run when the condition becomes true.
    where : tuple of :class:`~yasuki_core.engine.rules.vocabulary.locations.CardLocation`
        Where the card must be for the watch to be read.
    ruleset : str or None
        The one ruleset the watch is read under, or None for every arc.
    """

    key: str
    condition: WatchedCondition
    reaction: Trigger
    where: tuple[CardLocation, ...]
    ruleset: str | None


# printed id -> the conditions a copy of it watches. Read each time the board settles.
_WATCHES: dict[str, list[Watch]] = {}


def watch(
    printed_id: str,
    *,
    key: str,
    condition: WatchedCondition,
    reaction: Trigger,
    where: tuple[CardLocation, ...] = (CardLocation.HAND,),
    ruleset: str | None = None,
) -> None:
    """Run ``reaction`` for a copy of ``printed_id`` each time ``condition`` becomes true while the
    copy is where ``where`` names, the way a triggered trait answers an event (CR, "If" Triggers).

    The condition becoming true is announced as :class:`~.ConditionFulfilled` in the cascade that
    made it so, so the reaction runs where any other triggered trait would. A copy arriving where
    the watch looks while the condition already holds is a new occurrence and is announced too.

    Parameters
    ----------
    printed_id : str
        The card's printed id.
    key : str
        Names the watch among the card's others.
    condition : callable
        Maps ``(game, card)`` to whether the condition holds for that copy right now.
    reaction : callable
        The trigger run when the condition becomes true, handed the announcement as its event.
    where : tuple of :class:`~yasuki_core.engine.rules.vocabulary.locations.CardLocation`, optional
        Where the copy must be for the watch to be read. Default the hand alone.
    ruleset : str, optional
        The name of the one ruleset the watch is in force under, for a card whose text differs
        between arcs. Default None, for a text every arc reads.
    """
    _WATCHES.setdefault(printed_id, []).append(Watch(key, condition, reaction, where, ruleset))


# event type -> triggers the rulebook itself takes, after every card's. A rulebook effect that
# follows an occurrence, such as the Honor loss after a dishonorable Personality dies, is a trigger
# with no card behind it, and it fires on the card the event names.
_RULEBOOK_TRIGGERS: dict[type, list[Trigger]] = {}


def rulebook_trigger(
    event_type: type, *, label: TriggerLabel = printed_trait
) -> Callable[[Trigger], Trigger]:
    """Register the decorated function as a rulebook trigger for ``event_type``, fired after the
    card triggers for the same event with the card the event names as its context card, and named
    to the active player by ``label``."""

    def register(trigger: Trigger) -> Trigger:
        _LABELS[trigger] = label
        _RULEBOOK_TRIGGERS.setdefault(event_type, []).append(trigger)
        return trigger

    return register


# A choice resolver turns the ids a Choose collected into the effects the choice produces, given the
# seat that answered. Keyed by a string so a paused ChooseCards names its resolver, keeping the
# pending decision replay-stable (a stored closure would not rebuild to an equal object).
# A resolver takes the board, the card that asked, what was picked, and the seat that picked it. A
# choice raised with ``resolver_context``, one step of a card that asks two questions in a row,
# passes that too, by keyword; a resolver only declares the parameter if its card supplies one.
Resolver = Callable[..., list[Effect]]
CHOICE_RESOLVERS: dict[str, Resolver] = {}


def choice_resolver(
    key: str, *, prompt: str | None = None, pick: str | None = None
) -> Callable[[Resolver], Resolver]:
    """Register the decorated function as the choice resolver named ``key``.

    Parameters
    ----------
    key : str
        The name a :class:`~yasuki_core.engine.rules.effects.Choose` uses to reach this resolver.
    prompt : str, optional
        Fixed wording to ask the seat with. It ignores what they have picked so far, so a line that
        must track the selection belongs in a ``DecisionRequest.prompt`` override instead. A choice
        with no registered wording falls back to a generic line naming only how many cards it
        wants. Default None.
    pick : str, optional
        What picking one card does, as "Put on the bottom of your deck", for a client to offer on
        the card itself. Default None, which offers "Choose".
    """

    def register(resolver: Resolver) -> Resolver:
        if key in CHOICE_RESOLVERS:
            raise ValueError(f"{key} already has a choice resolver")
        CHOICE_RESOLVERS[key] = resolver
        if prompt is not None:
            CHOICE_PROMPTS[key] = prompt
        if pick is not None:
            CHOICE_PICKS[key] = pick
        return resolver

    return register


def resolve_choice(
    game: GameState,
    resolver: str,
    source_id: str | None,
    chosen: tuple[str, ...],
    seat: PlayerId,
    resolver_context: tuple[str, ...] = (),
) -> list[Effect]:
    """The effects the choice resolver ``resolver`` makes of ``chosen``. The context is passed only
    when the choice carries one, so a resolver whose card asks a single question never declares a
    parameter it would not read."""
    context = {"resolver_context": resolver_context} if resolver_context else {}
    return CHOICE_RESOLVERS[resolver](game, source_id, chosen, seat, **context)


def at_cap(card: L5RCard, counter: Counter, cap: int) -> bool:
    """Whether ``card`` already holds ``cap`` or more of ``counter``, a shared trigger guard."""
    return card.counters.get(counter.key, 0) >= cap


def caused_by(ctx: TriggerContext, seat: PlayerId) -> bool:
    """Whether ``seat``'s own action caused the event. The "if the action was yours" guard. Reads
    the event's ``cause``. Only meaningful for events that carry one. False when the rulebook or a
    card's trait caused it, since neither is an action."""
    return ctx.event.cause is seat


def apply_effect(game: GameState, effect: Effect) -> list[GameEvent]:
    """Commit one effect and return the events it raises, for the fixpoint walk to drain. This is
    the single mutation boundary. Triggers themselves never mutate."""
    return effect.perform(game)


def _departed_subject(game: GameState, event: GameEvent) -> L5RCard | None:
    """The card whose own departure ``event`` announces, once it has left the battlefield.

    A card is already in its discard by the time its destruction is announced, so this is the only
    way "after this card is destroyed" can ever fire.

    Departures only. A card off the battlefield takes no part in anything else that names it.
    A Personality killed by a state-based action as he arrived must not go on to take his
    enter-play trait, which is the whole point of settling those rules before the arrival is
    announced. A *created* card is never here either. It leaves the table outright, taking its
    printed id with it.
    """
    if not isinstance(event, Destroyed | CardDiscarded):
        return None
    card = game.table.cards_by_id.get(event.card_id)
    if card is None or any(held is card for held in game.table.battlefield.cards):
        return None
    return card


def _collect(game: GameState, event: GameEvent) -> list[tuple[L5RCard, Trigger]]:
    """The ``(card, trigger)`` pairs ``event`` fires: the cards' in canonical order, then the
    rulebook's and the delayed effects waiting for it, each on the card the event names. A watched
    condition is answered by its own watch alone."""
    if isinstance(event, ConditionFulfilled):
        return _watch_reactions(game, event)
    firing = [*_card_triggers(game, event), *_granted_triggers(game, event)]
    firing.sort(key=_canonical_order)
    rulebook = _RULEBOOK_TRIGGERS.get(type(event))
    if rulebook:
        subject = _named_subject(game, event)
        if subject is not None:
            firing.extend((subject, trigger) for trigger in rulebook)
    firing.extend(_held_until(game, event))
    return firing


@dataclass(frozen=True, slots=True)
class _Held:
    """A delayed effect waiting for the next time an event names a card, fired as a reaction to
    that event and taken out of ``game.delayed`` as it fires. A value, so a cascade paused with it
    still to fire replays equal."""

    until: NextTime
    effect: Effect

    def __call__(self, ctx: TriggerContext) -> list[Effect]:
        return [self.effect]


def _held_until(game: GameState, event: GameEvent) -> list[tuple[L5RCard, Trigger]]:
    """The delayed effects ``event`` is the occurrence of, each on the card the event names."""
    subject = _named_subject(game, event)
    if subject is None:
        return []
    return [
        (subject, _Held(until, effect))
        for until, effect in game.delayed
        if isinstance(until, NextTime) and until.matches(event)
    ]


def _granted_triggers(game: GameState, event: GameEvent) -> list[tuple[L5RCard, Trigger]]:
    """The triggers the card ``event`` names has been given for ``event``, wherever it now is: by
    the granting cards in play, and by the effects of granting cards that have since left play."""
    by_source = _GRANTED_TRIGGERS.get(type(event))
    if not by_source:
        return []
    subject = _named_subject(game, event)
    if subject is None:
        return []
    granted_here = [
        (subject, granted.trigger)
        for source in game.table.battlefield.cards
        for granted in by_source.get(source.printed_id, ())
        if in_force(granted) and granted.reaches(game, source, subject)
    ]
    return granted_here + [
        (subject, granted.trigger)
        for source in _departed_grantors(game, subject)
        for granted in by_source.get(source.printed_id, ())
        if in_force(granted) and granted.reaches is given_by_effect
    ]


def _departed_grantors(game: GameState, card: L5RCard) -> list[L5RCard]:
    """The cards off the battlefield whose effects have given ``card`` a grant still in force."""
    grantors = {
        recorded.source_id
        for recorded in game.ongoing
        if isinstance(recorded, AbilityGrant)
        and recorded.target_id == card.id
        and grant_applies(game, recorded)
    }
    if not grantors:
        return []
    grantors.difference_update(held.id for held in game.table.battlefield.cards)
    return [game.table.cards_by_id[source_id] for source_id in grantors]


def _card_triggers(game: GameState, event: GameEvent) -> list[tuple[L5RCard, Trigger]]:
    by_zone = _TRIGGERS.get(type(event))
    if not by_zone:
        return []
    in_play = by_zone.get(CardLocation.BATTLEFIELD, {})
    firing = [
        (card, trigger)
        for card in game.table.battlefield.cards
        for trigger in _read_triggers(in_play, card, event)
    ]
    # A departed card answers only for its own leaving, and for nothing that happens after.
    departed = _departed_subject(game, event)
    if departed is not None:
        firing.extend((departed, trigger) for trigger in _read_triggers(in_play, departed, event))
    in_hand = by_zone.get(CardLocation.HAND)
    if in_hand:
        firing.extend(
            (card, trigger)
            for seat in game.table.seats
            for card in game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards
            for trigger in _read_triggers(in_hand, card, event)
        )
    return firing


def _read_triggers(
    by_card: dict[str, list[Registration]], card: L5RCard, event: GameEvent
) -> list[Trigger]:
    """``card``'s registered triggers that the active ruleset reads and that answer this firing."""
    return [
        held.trigger
        for held in by_card.get(card.printed_id, ())
        if in_force(held) and _answers_this_edge(held, event)
    ]


def _answers_this_edge(held: Registration, event: GameEvent) -> bool:
    """Whether ``held`` answers this firing of an event announced at both edges of its own step. A
    registration for one edge is silent at the other."""
    return held.boundary is None or held.boundary is getattr(event, "boundary", None)


def _named_subject(game: GameState, event: GameEvent) -> L5RCard | None:
    """The card ``event`` names, wherever it now is, or None for an event about no card."""
    card_id = getattr(event, "card_id", None)
    return None if card_id is None else game.table.cards_by_id.get(card_id)


def _canonical_order(pair: tuple[L5RCard, Trigger]) -> tuple[str, str]:
    card = pair[0]
    return (card.owner.name if card.owner else "", card.id)


@dataclass(slots=True)
class _Effects:
    """Effects a walk still has to apply, in order, and where they came from. A ``simultaneous``
    frame is a group's, whose events gather in the events frame beneath it. ``announced`` holds the
    cards whose destruction has been announced and has not yet committed."""

    pending: list[Effect]
    provenance: Provenance
    simultaneous: bool = False
    announced: frozenset[str] = frozenset()


@dataclass(slots=True)
class _Events:
    """One occurrence's events still to announce, the triggered traits they triggered still to
    fire, each with the event it answers, the trigger the active player named to fire next, the
    events of the occurrence that follows this one, announced once this one has resolved, and
    whether the active player is ordering this occurrence's triggers."""

    queue: list[GameEvent]
    firing: list[tuple[L5RCard, Trigger, GameEvent]] = field(default_factory=list)
    chosen: str | None = None
    following: list[GameEvent] = field(default_factory=list)
    ordering: bool = False


_Frame = _Effects | _Events


def _begin(
    game: GameState,
    effects: Sequence[Effect] = (),
    queue: Sequence[GameEvent] = (),
    provenance: Provenance = Provenance(),
) -> None:
    """Walk a cascade from ``effects`` to apply and ``queue`` to react to."""
    _advance(game, [_Events(list(queue)), _Effects(list(effects), provenance)])


def _advance(game: GameState, frames: list[_Frame]) -> None:
    """Run the effect-and-trigger cascade to a fixpoint over ``frames``, the stack of work it still
    holds, bottom first.

    An effects frame applies its next effect, which commits at once. The events it raised become an
    events frame on top, so every trait they trigger resolves, nested triggers included, before the
    next effect applies (CR 20F, Timing: "Once a triggered trait starts, activate all its costs,
    targeting, and effects in sequence before proceeding, even if another action or triggered trait
    is under way"). What the state-based rules then demand of the board is the occurrence that
    follows, announced once that frame's triggers have resolved. A :class:`~.Simultaneously` group
    is the exception: its members' events gather in one events frame beneath the group, which fires
    once every member has happened. An effect something acts before, a destruction a trait reads
    "before this card is destroyed", is announced first as an events frame of its own, read as the
    Interrupt modifications and the negations in force will leave it, and commits once that frame
    has resolved. A group's destructions are announced together, as one occurrence, before any
    member commits. A destruction the state-based rules demand is not announced. An events frame
    announces all of its occurrence's events and collects every trait they trigger, dropping those
    that would do nothing when several were collected. While the triggers left belong to two or more
    cards outside a hand, it pauses for the active player's :class:`~.ChooseNextTrigger` (CR, Timing
    Conflicts). Otherwise it fires the next as a new effects frame, unless its card has since left
    where it answers from. A frame with nothing left is dropped, and the walk ends with the stack.
    An :class:`~.InterruptingEffect` pauses the walk: it stashes the exact remainder (every frame,
    the paused one holding the effects after the one that asked) as a :class:`~.ResumeCascade` and
    records that effect's decision, so :func:`~.resume_cascade` continues from precisely here once
    the seat answers. An effect with nothing to ask leaves the stash to drain behind the work it
    queued.

    Each effects frame carries the provenance of its effects. Its ``interruptible`` says they are an
    action's own, the only ones an Interrupt may modify (ShE datasheet, Interrupt). Each is checked
    against the modifications the action's :class:`~.InterruptWindow` collected before it is
    applied, and resolves as what the Interrupt made of it. What a trigger returns is a trait's or
    the rulebook's, never the action's, so it is applied as returned.

    Every effect, an action's or not, is checked against the negations in force as it commits,
    whatever produced it, since a negation makes an effect fail to happen whenever it would occur
    (CR, Prevention). The check comes before an effect pauses, so a negated discard asks nothing.
    The provenance's ``acting`` names the card whose action produced the effects in hand, which a
    negation naming a source reads, and its ``negations`` are the ones that action spent. A pause
    and what an effect produces keep both, and a trigger's effects carry neither. The provenance's
    ``paying`` says the effects in hand are a cost's payments instead, which are no effects (CR,
    Effects), so no negation reaches them. What reacts to them is effects again.

    The provenance's ``triggered`` says the effects in hand are a trigger's, so a decision among
    them is marked as the trigger's question, one that cannot be backed out of. The walk sets it on
    the effects frame of each trigger it fires for an event that has happened, and a stash carries
    it on to the effects that follow. A trigger firing in a window a step opens
    before committing asks on the step's behalf, and its question stays the step's own."""
    resolved = 0
    while frames:
        top = frames[-1]
        if isinstance(top, _Effects):
            if not top.pending:
                frames.pop()
                continue
            popped = effect = top.pending.pop(0)
            provenance = top.provenance
            contingent: tuple[Effect, ...] = ()
            if isinstance(effect, To):
                _trace.append(f"    {effect.describe()}")
                contingent = effect.contingent
                effect = effect.first
            first = effect
            if isinstance(effect, Simultaneously):
                _trace.append(f"    {effect.describe()}")
                if top.simultaneous:
                    top.pending[:0] = effect.effects
                else:
                    frames.append(_Events([]))
                    group = _Effects(list(effect.effects), provenance, simultaneous=True)
                    frames.append(group)
                    announcing = _group_impending(game, effect.effects, provenance)
                    if announcing:
                        group.announced = frozenset(event.card_id for event in announcing)
                        frames.append(_Events(list(announcing)))
                continue
            if isinstance(effect, Attributed):
                # Stashed beneath it, so the effects around it keep their order.
                _stash(game, frames)
                game.stack.append(ApplyEffects((effect.effect,), effect.provenance))
                return
            stands = as_modified(game, effect) if _modifiable(effect, provenance) else effect
            impending = stands.impending(game)
            unannounced = [event for event in impending if event.card_id not in top.announced]
            if any(_collect(game, event) for event in unannounced) and not _will_be_negated(
                game, stands, provenance
            ):
                top.announced |= {event.card_id for event in unannounced}
                top.pending.insert(0, popped)
                frames.append(_Events(unannounced))
                continue
            if _modifiable(effect, provenance):
                effect = _modified(game, effect)
            if not provenance.paying:
                effect = negate_committed(game, effect, provenance)
            effect = _held_from(effect, provenance)
            if isinstance(effect, InterruptingEffect) and effect.pauses(game):
                if effect.answers_in_place:
                    # Kept where it stood, with what depends on it, for the answer to replace.
                    top.pending.insert(0, popped)
                # Stash before asking for the request: the work stack is LIFO, and an effect whose
                # request queues its own work (a recruit queues its resolution) must have that work
                # run before the remainder of this cascade resumes.
                _stash(game, frames)
                request = effect.request(game)
                if request is not None:
                    game.pending = (
                        replace(request, triggered=True) if provenance.triggered else request
                    )
                return
            _trace.append(f"    {effect.describe()}")
            happens = bool(contingent) and happens_as(game, first, effect)
            raised = apply_effect(game, effect)
            # A group's frame holds every member's announcement, so only this member's leaves. Any
            # other frame announced at most the effect it put back at its head, which this is.
            if top.simultaneous:
                top.announced -= {event.card_id for event in impending}
            else:
                top.announced = frozenset()
            # What the effect produced goes next, ahead of the rest, so an attack's outcome resolves
            # where the attack stood and passes through the Interrupt step on its own.
            top.pending[:0] = (*effect.follow_on(game), *(contingent if happens else ()))
            # What the rules demand of the board the effect left is the next occurrence, so its
            # events follow the effect's own once their triggers have resolved.
            demanded: list[GameEvent] = []
            _settle_state_based_actions(game, demanded)
            # A condition the effect itself made true is part of its occurrence, so a Ring that
            # enters on it is offered alongside whatever else the effect set off. One a
            # state-based action made true follows with that action.
            if all(isinstance(event, ConditionFulfilled) for event in demanded):
                raised, demanded = [*raised, *demanded], []
            if top.simultaneous:
                group = _group_events(frames)
                group.queue.extend(raised)
                group.following.extend(demanded)
            elif raised or demanded:
                frames.append(_Events(raised, following=demanded))
            continue
        top.firing = _still_collected(game, top.firing)
        if top.firing:
            public = _public(game, top)
            entry_offer_first = _in_hand(game, top.firing[0][0])
            ordering = top.ordering or len(public) > 1
            if top.chosen is None and public and ordering and not entry_offer_first:
                idle = [entry for entry in public.values() if not _acts(game, entry)]
                if idle:
                    top.firing = [entry for entry in top.firing if entry not in idle]
                    continue
                top.ordering = True
                _stash(game, frames)
                game.pending = _trigger_window(game, public)
                return
            card, trigger, event = top.firing.pop(0)
            top.chosen = None
            if isinstance(trigger, _Held):
                game.delayed.remove((trigger.until, trigger.effect))
            _trace.append(f"  {card.printed_id} ({card.id}) reacts")
            effects = list(trigger(TriggerContext(game, card, event)))
            frames.append(_Effects(effects, Provenance(triggered=not opens_a_window(event))))
            continue
        if not top.queue and top.following:
            top.queue, top.following = top.following, []
        if not top.queue:
            # The walk can be entered on a board something else already made illegal, and with
            # nothing to commit the per-effect check never runs. Judge it before returning.
            _settle_state_based_actions(game, top.queue)
            if not top.queue:
                frames.pop()
                continue
        top.ordering = False
        while top.queue:
            resolved += 1
            if resolved > _MAX_CASCADE:
                raise RuntimeError(
                    f"trigger cascade did not converge after {_MAX_CASCADE} events:\n"
                    f"{_render_trace()}"
                )
            event = top.queue.pop(0)
            _announce(game, event)
            top.firing.extend((card, trigger, event) for card, trigger in _collect(game, event))
        if len(top.firing) > 1:
            top.firing = _triggered(game, top.firing)


def _group_impending(
    game: GameState, effects: tuple[Effect, ...], provenance: Provenance
) -> list[Destroying]:
    """What is announced before a :class:`~.Simultaneously` group of ``effects`` commits, as one
    occurrence: each member read as the Interrupts and the negations in force will leave it, a
    ``once`` negation hiding only the first member it will spend itself on. Empty when nothing
    answers any of it. A member the forecast misses is announced as it comes up."""
    members = [
        as_modified(game, member) if _modifiable(member, provenance) else member
        for member in _group_members(effects)
    ]
    impending = [(member, member.impending(game)) for member in members]
    if not any(_collect(game, event) for _, events in impending for event in events):
        return []
    spent: list[Negation] = []
    return [
        event
        for member, events in impending
        if provenance.paying or not would_negate(game, member, provenance, spent)
        for event in events
    ]


def _group_members(effects: tuple[Effect, ...]) -> Iterator[Effect]:
    """The effects a group commits, a nested group's among them, and the first of a :class:`~.To`,
    whose dependent effects are not known until it has happened."""
    for effect in effects:
        if isinstance(effect, Simultaneously):
            yield from _group_members(effect.effects)
        else:
            yield effect.first if isinstance(effect, To) else effect


def _will_be_negated(game: GameState, stands: Effect, provenance: Provenance) -> bool:
    """Whether a negation in force will negate ``stands``, an effect as the Interrupts leave it,
    read without spending one. A negated effect is announced to nothing, since the negation
    happens first (ShE datasheet, The Yu Trait)."""
    return not provenance.paying and would_negate(game, stands, provenance, [])


def _modifiable(effect: Effect, provenance: Provenance) -> bool:
    """Whether the Interrupts taken against the action can modify ``effect``: one of the action's
    own effects, other than a question it asks."""
    return provenance.interruptible and not isinstance(effect, InterruptingEffect)


def happens_as(game: GameState, first: Effect, committing: Effect) -> bool:
    """Whether ``committing``, what the checks made of ``first``, is ``first`` actually happening:
    the same kind of effect on the same card, which an Interrupt's adjustment leaves it and a
    negation or substitution does not, and one that would change something."""
    if type(committing) is not type(first) or committing.subject_id != first.subject_id:
        return False
    return committing.would_happen(game)


def _group_events(frames: list[_Frame]) -> _Events:
    """The events frame beneath the group on top of the stack, which gathers what its members
    raise."""
    beneath = frames[-2]
    if not isinstance(beneath, _Events):
        raise RuntimeError("a group's effects frame has no events frame beneath it")
    return beneath


def _announce(game: GameState, event: GameEvent) -> None:
    """Record ``event`` as having happened this turn, and as the action's doing where it is."""
    game.turn_events += (event,)
    # Kept for the Response Step, which asks what the action it follows actually did. What an
    # Interrupt or a Response does inside its own round is its doing, not the action's, and the
    # announcement that the action resolved is about it rather than by it.
    inside_a_step = game.round.kind in STEP_ROUNDS
    if not inside_a_step and not isinstance(
        event, ActionResolved | ConditionFulfilled | Destroying
    ):
        game.action_events.append(event)
    _trace.append(type(event).__name__)


_Firing = tuple[L5RCard, Trigger, GameEvent]


def _still_collected(game: GameState, firing: list[_Firing]) -> list[_Firing]:
    """The entries of ``firing`` whose event would still collect their trigger from their card,
    which a card that has since left where it answers from no longer does. Each event is
    collected once, however many entries answer it."""
    collected: dict[int, list[tuple[L5RCard, Trigger]]] = {}
    kept: list[_Firing] = []
    for entry in firing:
        card, trigger, event = entry
        pairs = collected.get(id(event))
        if pairs is None:
            pairs = collected[id(event)] = _collect(game, event)
        if any(held is card and answer == trigger for held, answer in pairs):
            kept.append(entry)
    return kept


def _acts(game: GameState, entry: _Firing) -> bool:
    """Whether ``entry`` would do something on the board as it now stands, which a trigger whose
    condition an earlier one undid no longer does. Handlers never change the board, so asking one
    is safe."""
    card, trigger, event = entry
    return bool(list(trigger(TriggerContext(game, card, event))))


def _triggered(game: GameState, firing: list[_Firing]) -> list[_Firing]:
    """The triggered traits in ``firing`` whose condition the occurrence met, which return effects
    on the board it left, those of cards in a hand first. A trait that returns nothing was not
    triggered, whatever a sibling's resolution makes of the board later. A card in a hand answers
    only to offer entering play, which may follow its condition immediately and may not be delayed
    (CR, Ring), so it is offered before any other trait resolves or any order is asked. Handlers
    never change the board, so asking one is safe."""
    acting = [
        (card, trigger, event)
        for card, trigger, event in firing
        if list(trigger(TriggerContext(game, card, event)))
    ]
    return sorted(acting, key=lambda entry: not _in_hand(game, entry[0]))


def _in_hand(game: GameState, card: L5RCard) -> bool:
    return any(
        card in game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards for seat in game.table.seats
    )


def _public(game: GameState, frame: _Events) -> dict[str, _Firing]:
    """The triggers still to fire that the active player may see, in collection order, each keyed
    by its card's id, with ``#n`` appended where the card has more than one."""
    seen = [entry for entry in frame.firing if not _in_hand(game, entry[0])]
    per_card = collections.Counter(card.id for card, _, _ in seen)
    counted: collections.Counter[str] = collections.Counter()
    keyed: dict[str, _Firing] = {}
    for entry in seen:
        card_id = entry[0].id
        counted[card_id] += 1
        key = card_id if per_card[card_id] == 1 else f"{card_id}#{counted[card_id]}"
        keyed[key] = entry
    return keyed


def _trigger_window(game: GameState, public: dict[str, _Firing]) -> ChooseNextTrigger:
    """The active player's window over ``public``: each trigger with its card and label."""
    return ChooseNextTrigger(
        seat=game.active,
        candidates=tuple(public),
        cards=tuple(card.id for card, _, _ in public.values()),
        labels=tuple(trigger_label(game, card, trigger) for card, trigger, _ in public.values()),
    )


def _held_from(effect: Effect, provenance: Provenance) -> Effect:
    """``effect``, with the effect a delay holds wrapped in :class:`~.Attributed` when an action
    from a card schedules it, so it resolves as that action's. Anything else is returned unchanged.
    """
    if not isinstance(effect, DelayedEffect) or provenance.acting is None:
        return effect
    action = Provenance(acting=provenance.acting, negations=provenance.negations)
    return replace(effect, effect=Attributed(effect.effect, action))


def as_modified(game: GameState, effect: Effect) -> Effect:
    """``effect`` as the Interrupts taken against the action will have it resolve, read without
    spending them: every modification bound to it applies in the order the Interrupts were taken.
    One that would negate an effect that cannot be negated changes nothing."""
    original = effect
    for modification in game.modifications:
        if modification.answers(original):
            modified = modification.apply(game, effect)
            if not (isinstance(modified, Negated) and not effect.is_negatable(game)):
                effect = modified
    return effect


def _modified(game: GameState, effect: Effect) -> Effect:
    """``effect`` as :func:`as_modified` reads it, spending every modification bound to it."""
    modified = as_modified(game, effect)
    game.modifications[:] = [m for m in game.modifications if not m.answers(effect)]
    return modified


def _refuse_mid_decision(game: GameState, driver: str) -> None:
    """Raise ``RuntimeError`` if a decision is pending, naming ``driver`` and the request.

    A cascade driven over an open question would overwrite the request the moment it paused, and
    the question would be lost without anything failing.
    """
    if game.pending is not None:
        raise RuntimeError(
            f"{driver} drove a cascade while {type(game.pending).__name__} is pending"
        )


def enforce_state_based_actions(game: GameState) -> None:
    """Satisfy the state-based rules against the board as it stands, resolving what that raises.

    For the board changes the cascade does not make (a card placed on the battlefield by
    ``flow``, a modifier expiring at a turn boundary), the walk enforces the rules after each
    effect it commits: how a caller that mutated the board directly gets the same guarantee.

    Raise ``RuntimeError`` if a decision is pending.
    """
    _refuse_mid_decision(game, "enforce_state_based_actions")
    queue: list[GameEvent] = []
    _settle_state_based_actions(game, queue)
    if queue:
        _begin(game, queue=queue)


def lapse_ongoing(game: GameState, moment: Moment) -> None:
    """Drop the ongoing records that last until ``moment``, now the flow has reached it, and
    satisfy the state-based rules against the board their expiry leaves.

    An expiring stat change can make the board illegal with no effect committing, as a Chi bonus
    ending under a Personality does, so nothing else would catch it. Settling it may ask a
    question, so a caller queues what follows the moment before calling this.

    Raise ``RuntimeError`` if a decision is pending.
    """
    if _lapse(game, moment):
        enforce_state_based_actions(game)


def reach_moment(game: GameState, moment: Moment, *announcing: GameEvent) -> None:
    """Lapse the ongoing records that last until ``moment``, then resolve the effects held until
    it, as one cascade that first settles the board the lapse leaves and then announces
    ``announcing``, the events that mark the moment.

    One cascade, so a question any part of it asks pauses the rest rather than being overtaken.

    Raise ``RuntimeError`` if a decision is pending.
    """
    _refuse_mid_decision(game, "reach_moment")
    _lapse(game, moment)
    held = _take_held(game, moment)
    settled: list[GameEvent] = []
    _settle_state_based_actions(game, settled)
    _advance(game, [_Events(settled, following=list(announcing)), _Effects(held, Provenance())])


def _lapse(game: GameState, moment: Moment) -> bool:
    """Drop the ongoing records that last until ``moment``, saying whether any did."""
    kept = [recorded for recorded in game.ongoing if not _lapses_at(recorded.duration, moment)]
    lapsed = len(kept) < len(game.ongoing)
    game.ongoing = kept
    return lapsed


def _lapses_at(duration: Lifetime, moment: Moment) -> bool:
    """Whether a record lasting for ``duration`` ends at ``moment``. The end of the turn ends
    every one but the two that outlast it: an ongoing effect lasts until the end of the turn unless
    it says otherwise (CR, Duration of Effects), and a phase or a battle does not outlast its turn,
    so a record whose moment the turn never reached ends there too."""
    if moment == END_OF_TURN:
        return duration not in (Duration.WHILE_SOURCE_IN_PLAY, Duration.PERMANENT)
    return duration == moment


def _forget_ongoing_on_cards_off_the_table(game: GameState) -> None:
    """Drop ongoing records whose target has left the battlefield and the Provinces.

    A card that leaves play ceases to exist (CR), so nothing granted to it outlives the departure,
    ``PERMANENT`` included, whose permanence is against its *source* going away rather than its
    target. A Province card counts as still on the table. Repairing the Ruins raises a Holding's
    Gold Cost while it waits in one, and that has to survive being Recruited out of it. A focused
    card counts too, so that a card raising another's Focus Value survives to the reveal that totals
    it. The duel discards what it focused, which is what ends those changes (CR, Duel).

    Forgotten rather than skipped when read: a card can return to a Province, and a record merely
    filtered out would come back attached to the card that replaced it. One laid on a condition, a
    Province slot or a player is kept whatever happens: none of those is a card that can leave the
    table. A negation is forgotten with the card it names, and kept when it names none (CR, Card
    Memory Rule).
    """
    if not game.ongoing:
        return
    # A card announced from hand stands in the area a card entering play waits in while its costs
    # are checked and paid (CR, Entering-Play Areas), so what was laid on it then, an Invest among
    # them, reaches play with it.
    on_table = {card.id for card in game.table.battlefield.cards} | game.announced_from_hand
    for key, zone in game.table.zones.items():
        if key.role in (ZoneRole.PROVINCE, ZoneRole.FOCUS):
            on_table.update(card.id for card in zone.cards)
    game.ongoing[:] = [record for record in game.ongoing if _names_no_card_off(record, on_table)]


def _names_no_card_off(record: Ongoing, on_table: set[str]) -> bool:
    """Whether ``record`` names no card that is off the table."""
    match record:
        case ConditionalModifier() | ProvinceModifier() | LobbyModifier() | SeatAbilityGrant():
            return True
        case Negation(subject_id=subject_id):
            return subject_id is None or subject_id in on_table
        case CompassionGrant(card_id=card_id):
            return card_id is None or card_id in on_table
        case _:
            return record.target_id in on_table


def _settle_state_based_actions(game: GameState, queue: list[GameEvent]) -> None:
    """Satisfy every state-based rule before anything else happens, queueing what the enforcement
    raises.

    These rules are conditions the board must satisfy at all times rather than reactions to an
    event, so the ordering is the rule: enforced after each committed effect rather than once the
    cascade settles, an illegal board never survives long enough for anything to read it. Nothing
    commits behind the change that broke a condition, no trigger fires on the broken state, and the
    walk cannot pause for a decision while it stands, because the pause is tested before an effect
    applies and every applied effect has already been judged.

    Enforcement runs to its own fixpoint: satisfying one condition can break another, and the CR's
    conditions chain that way by design. A destroyed card can orphan what was attached to it, and
    a seat losing its last Province loses the game. Each round begins by forgetting the ongoing
    records of whatever the last one drove off the table, so no rule reads a stat off a card
    that has gone.

    A state-based action is not checked against a lasting negation: one it stopped would be
    demanded again on every round, so the enforcement would never settle. A rule that a continuous
    effect can hold off asks before demanding instead, as Chi death does. A ``once`` negation is
    spent on the action and negates it for that round, and the rule demands it again on the next.
    """
    for _ in range(_MAX_CASCADE):
        _forget_ongoing_on_cards_off_the_table(game)
        demanded = state_based_actions.demanded(game)
        if not demanded:
            queue.extend(_newly_fulfilled(game))
            return
        for effect in demanded:
            effect = spend_once(game, effect)
            _trace.append(f"    {effect.describe()} (state-based action)")
            queue.extend(apply_effect(game, effect))
    raise RuntimeError(
        f"state-based actions did not settle after {_MAX_CASCADE} rounds:\n{_render_trace()}"
    )


def _watched_cards(game: GameState) -> Iterator[tuple[CardLocation, L5RCard]]:
    """Each card in a hand, on the battlefield or in a Province, with where it is."""
    for seat in game.table.seats:
        for card in game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards:
            yield CardLocation.HAND, card
    for card in game.table.battlefield.cards:
        yield CardLocation.BATTLEFIELD, card
    for key, zone in game.table.zones.items():
        if key.role is ZoneRole.PROVINCE:
            for card in zone.cards:
                yield CardLocation.PROVINCE, card


def _reading(watches: Sequence[Watch], location: CardLocation) -> Iterator[Watch]:
    return (each for each in watches if location in each.where and in_force(each))


def _newly_fulfilled(game: GameState) -> list[ConditionFulfilled]:
    """Record which watched conditions hold on the settled board, and announce each that did not
    hold when the board last settled (CR, "If" Triggers).

    Nothing is judged while a card announced out of a hand waits in its entering-play or resolution
    area: the board it leaves behind is mid-action, between the announcement and the card landing
    or returning. The next settle after that compares against the board from before the
    announcement, so a condition still fulfilled once the card has landed is announced then.
    """
    if game.announced_from_hand:
        return []
    if not _WATCHES and not game.conditions_holding:
        return []
    holding = [
        (card.id, each.key)
        for location, card in _watched_cards(game)
        if card.printed_id in _WATCHES
        for each in _reading(_WATCHES[card.printed_id], location)
        if each.condition(game, card)
    ]
    fulfilled = [
        ConditionFulfilled(card_id, key)
        for card_id, key in holding
        if (card_id, key) not in game.conditions_holding
    ]
    game.conditions_holding = frozenset(holding)
    return fulfilled


def _watch_reactions(game: GameState, event: ConditionFulfilled) -> list[tuple[L5RCard, Trigger]]:
    """The reaction of the watch ``event`` announces, while its card is still where it looks."""
    card = game.table.cards_by_id.get(event.card_id)
    location = next((where for where, each in _watched_cards(game) if each is card), None)
    if card is None or location is None:
        return []
    return [
        (card, each.reaction)
        for each in _reading(_WATCHES.get(card.printed_id, ()), location)
        if each.key == event.key
    ]


def _render_trace() -> str:
    """The tail of the walk as an indented trace, with any repeating cycle collapsed to one copy.

    A non-converging cascade repeats the same handful of steps, so printing sixty of them buries the
    answer. Naming the shortest repeating block and how many times it recurred is the diagnosis.
    """
    lines = list(_trace)
    for length in range(1, len(lines) // 2 + 1):
        cycle = lines[-length:]
        repeats = 1
        while lines[-length * (repeats + 1) : -length * repeats] == cycle:
            repeats += 1
        if repeats > 1:
            return "\n".join(
                [*cycle, f"  ... repeating, {repeats} times in the last {len(lines)} steps"]
            )
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class EffectsFrame:
    """Effects a paused cascade still has to apply, and where they came from.

    Attributes
    ----------
    effects : tuple of Effect
        The effects still to apply, in order.
    provenance : Provenance, optional
        Where they came from. Default a rulebook procedure's.
    simultaneous : bool, optional
        Whether they are the rest of a :class:`~.Simultaneously` group, whose events gather in the
        events frame beneath. Default False.
    announced : frozenset of str, optional
        The cards whose destruction has been announced and has not yet committed. Default none.
    """

    effects: tuple[Effect, ...]
    provenance: Provenance = Provenance()
    simultaneous: bool = False
    announced: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class EventsFrame:
    """One occurrence a paused cascade still has to announce and fire triggered traits for.

    Attributes
    ----------
    queue : tuple of GameEvent
        The occurrence's events still to announce.
    firing : tuple of (str, callable, GameEvent), optional
        The card id, trigger and event of each triggered trait still to fire. Default none.
    chosen : str or None, optional
        The trigger the active player named, which stands first. Default None.
    following : tuple of GameEvent, optional
        The events of the occurrence that follows this one. Default none.
    ordering : bool, optional
        Whether the active player is ordering this occurrence's triggers, and so is asked for each
        until none they may see is left. Default False.
    """

    queue: tuple[GameEvent, ...]
    firing: tuple[tuple[str, Trigger, GameEvent], ...] = ()
    chosen: str | None = None
    following: tuple[GameEvent, ...] = ()
    ordering: bool = False


@dataclass(frozen=True, slots=True)
class ResumeCascade:
    """The exact remainder of an effect-and-trigger cascade a choice paused, as the stack of frames
    it still held, bottom first. The top frame holds the effects after the one that raised the
    choice, and the answered choice's own effects splice in ahead of them. It is ephemeral like the
    rest of the stack, since its effects and triggers are value-equal and stable module-level
    functions, so it rebuilds and compares equal under replay.

    Attributes
    ----------
    frames : tuple of EffectsFrame or EventsFrame
        The paused cascade's frames, bottom first.
    """

    frames: tuple[EffectsFrame | EventsFrame, ...]

    def resume(self, game: GameState) -> None:
        # An interrupting effect whose answer produces no effects of its own, a payment, say, leaves
        # its stash here for the generic drain. A Choose goes through `resume_paused_cascade`, which
        # splices the resolver's effects in.
        resume_cascade(game, self, [])


def _stash(game: GameState, frames: list[_Frame]) -> None:
    game.stack.append(ResumeCascade(tuple(_frozen(frame) for frame in frames)))


def _frozen(frame: _Frame) -> EffectsFrame | EventsFrame:
    if isinstance(frame, _Effects):
        return EffectsFrame(
            tuple(frame.pending), frame.provenance, frame.simultaneous, frame.announced
        )
    firing = tuple((card.id, trigger, event) for card, trigger, event in frame.firing)
    return EventsFrame(
        tuple(frame.queue), firing, frame.chosen, tuple(frame.following), frame.ordering
    )


def _thawed(game: GameState, frame: EffectsFrame | EventsFrame) -> _Frame:
    """``frame`` for the walk to resume, dropping the triggers whose card has left the table."""
    if isinstance(frame, EffectsFrame):
        return _Effects(list(frame.effects), frame.provenance, frame.simultaneous, frame.announced)
    firing = [
        (game.table.cards_by_id[card_id], trigger, event)
        for card_id, trigger, event in frame.firing
        if card_id in game.table.cards_by_id
    ]
    return _Events(list(frame.queue), firing, frame.chosen, list(frame.following), frame.ordering)


def resume_cascade(game: GameState, item: ResumeCascade, produced: list[Effect]) -> None:
    """Continue a cascade an interrupting effect paused, splicing ``produced`` (the effects the
    answer produced) in where that effect stood, ahead of the effects, triggers, and events the
    pause stashed. Triggers whose card has since left play are dropped.

    Raise ``RuntimeError`` if the stash has no events frame at its bottom or no effects frame on
    top, which every pause leaves, before anything resumes.
    """
    frames = _resumed_frames(game, item)
    top = frames[-1]
    if not isinstance(top, _Effects):
        raise RuntimeError("a paused cascade resumed with no effects frame on top")
    top.pending[:0] = produced
    _advance(game, frames)


def _resumed_frames(game: GameState, item: ResumeCascade) -> list[_Frame]:
    """``item``'s frames for the walk to resume. Raise ``RuntimeError`` if there is no events frame
    at the bottom, which every stash has."""
    frames = [_thawed(game, frame) for frame in item.frames]
    if not isinstance(frames[0], _Events):
        raise RuntimeError("a paused cascade resumed with no events frame at the bottom")
    return frames


def _popped_stash(game: GameState) -> ResumeCascade:
    """The stash on top of the work stack, which a pause always leaves there. Raise
    ``RuntimeError`` if something else is."""
    item = game.stack.pop()
    if not isinstance(item, ResumeCascade):
        raise RuntimeError("an answer resumed without its stashed cascade")
    return item


@dataclass(frozen=True, slots=True)
class AnnounceEvent:
    """Announce ``event`` once the work queued above it has run, for a procedure that settles the
    board before telling anything a card arrived, where the settling may stop to ask a question.

    Attributes
    ----------
    event : GameEvent
        What to announce.
    """

    event: GameEvent

    def resume(self, game: GameState) -> None:
        fire(game, self.event)


@dataclass(frozen=True, slots=True)
class HeldAction:
    """An action's effects held at the Interrupt step, beneath the Interrupt round open over them.
    :func:`~yasuki_core.engine.rules.turn.sequence.run_stack` leaves it in place while that round
    is open, and once the round closes it resumes the action: the effects resolve as the
    Interrupts taken make of them.

    Attributes
    ----------
    effects : tuple of Effect
        The action's effects, in the order they will resolve.
    provenance : Provenance
        Where the action's effects come from.
    """

    effects: tuple[Effect, ...]
    provenance: Provenance

    def resume(self, game: GameState) -> None:
        _begin(game, self.effects, provenance=self.provenance)


def resume_paused_cascade(game: GameState, produced: list[Effect]) -> None:
    """Pop the cascade the answered choice paused and continue it with ``produced`` spliced in.

    The stash is always the top of the stack: a choice pauses the walk the moment it is raised, and
    nothing pushes between the pause and the answer. Raise ``RuntimeError`` if it is not there.
    """
    resume_cascade(game, _popped_stash(game), produced)


def resume_in_place(game: GameState, choices: tuple[str, ...]) -> None:
    """Pop the cascade a question answered in place paused, and continue it with what ``choices``
    make of that question where it stood, still the first of the :class:`~.To` it stood in.

    Raise ``RuntimeError`` if the stash does not hold such a question at the head of its top frame,
    where its pause leaves it.
    """
    frames = _resumed_frames(game, _popped_stash(game))
    top = frames[-1]
    held = top.pending.pop(0) if isinstance(top, _Effects) and top.pending else None
    asked = held.first if isinstance(held, To) else held
    if not isinstance(asked, InterruptingEffect) or not asked.answers_in_place:
        raise RuntimeError("an answer came back with no question paused to take it")
    answer = asked.answered(choices)
    top.pending.insert(0, To(answer, held.contingent) if isinstance(held, To) else answer)
    _advance(game, frames)


def resume_trigger_order(game: GameState, chosen: str) -> None:
    """Pop the cascade a :class:`~.ChooseNextTrigger` paused and continue it, firing the trigger
    keyed ``chosen`` first.

    Raise ``RuntimeError`` if the stash is not the top of the stack, holds no events frame on top,
    which that pause always leaves, or holds no trigger keyed ``chosen``.
    """
    frames = _resumed_frames(game, _popped_stash(game))
    top = frames[-1]
    if not isinstance(top, _Events):
        raise RuntimeError("a trigger order resumed with no events frame on top")
    entry = _public(game, top).get(chosen)
    if entry is None:
        raise RuntimeError(f"{chosen} has no trigger to resolve")
    top.firing.remove(entry)
    top.firing.insert(0, entry)
    top.chosen = chosen
    _advance(game, frames)


def fire(game: GameState, event: GameEvent) -> None:
    """Resolve ``event`` and the cascade it triggers, running the worklist to a fixpoint.

    The single-event case of :func:`~.fire_all`. Occurrences that happen at the same instant go
    through that one together; firing them one after another imposes an order the rules do not.

    Raise ``RuntimeError`` if a decision is pending.
    """
    _refuse_mid_decision(game, "fire")
    _begin(game, queue=(event,))


def fire_all(game: GameState, events: Sequence[GameEvent]) -> None:
    """Resolve ``events`` as one cascade, for occurrences that happen at the same instant.

    Firing them one at a time is not the same thing: a trigger that pauses for a decision leaves
    the machine stopped, and the next call would start a second cascade on top of the pending
    request and overwrite it.

    Raise ``RuntimeError`` if a decision is pending.
    """
    _refuse_mid_decision(game, "fire_all")
    _begin(game, queue=events)


def resolve_effects(
    game: GameState, effects: list[Effect], *, provenance: Provenance = Provenance()
) -> None:
    """Apply ``effects`` and run the derived-event cascade the same way :func:`~.fire` does, so a
    triggered reaction to those effects still resolves. The effects are not an action's own, so
    none is held at the Interrupt step: a rulebook procedure's effects, a trait's, and an
    Interrupt's own effects all come through here, and a cost through :func:`~.pay_costs`.
    ``provenance`` says where they came from.

    Raise ``ValueError`` if ``provenance`` names an action's own effects, which
    :func:`~.resolve_action_effects` resolves, and ``RuntimeError`` if a decision is pending.
    """
    if provenance.interruptible:
        raise ValueError("an action's own effects resolve through resolve_action_effects")
    _refuse_mid_decision(game, "resolve_effects")
    _begin(game, effects, provenance=provenance)


def pay_costs(game: GameState, costs: list[Effect]) -> None:
    """Pay ``costs`` and run the cascade their payment raises, as :func:`~.resolve_effects` does.
    A cost is no effect (CR, Effects), so no negation reaches it, and a decision it pauses on keeps
    the rest of it a cost when answered.

    Raise ``RuntimeError`` if a decision is pending.
    """
    _refuse_mid_decision(game, "pay_costs")
    _begin(game, costs, provenance=Provenance(paying=True))


def resolve_action_effects(
    game: GameState, effects: list[Effect], *, provenance: Provenance = Provenance()
) -> None:
    """Apply ``effects`` as an action's own, which is what step E of the Action Sequence hands
    over. The first effects an action hands over are held beneath an Interrupt round first (CR,
    Action Sequence step D), when any seat holds an Interrupt to take, and every effect resolves
    as the Interrupts taken there make of it. What the action hands over after that round, such as
    an effect a delay held, opens no second one. The derived-event cascade runs as in
    :func:`~.resolve_effects`. ``provenance`` says whose action this is, as
    :func:`~.action_provenance` builds it, and an action from no card by default.

    Raise ``RuntimeError`` if a decision is pending.
    """
    # Imported where it is used: the Interrupt step reads the hands and the round, and the module
    # that does so imports this one.
    from yasuki_core.engine.rules.interrupts import open_interrupt_window

    _refuse_mid_decision(game, "resolve_action_effects")
    provenance = replace(provenance, interruptible=True)
    if game.interrupts_offered:
        _begin(game, effects, provenance=provenance)
        return
    game.interrupts_offered = True
    held = HeldAction(tuple(effects), provenance)
    game.stack.append(held)
    if not open_interrupt_window(game):
        game.stack.pop()
        held.resume(game)


def action_did[E: GameEvent](game: GameState, kind: type[E]) -> tuple[E, ...]:
    """Every event of ``kind`` the action now resolving has produced, in the order it happened.

    What a Response reads to know what it is answering: "discarded a Fate card" and "Recruits this
    Holding" are facts about the action rather than about the board it leaves behind.
    """
    return tuple(event for event in game.action_events if isinstance(event, kind))


def action_recruited(game: GameState, card_id: str) -> bool:
    """Whether the action now resolving Recruited ``card_id``, as "after the action Recruits X"
    reads, rather than putting it into play some other way."""
    return any(
        event.recruited and event.card_id == card_id for event in action_did(game, EnteredPlay)
    )


def resolve_delayed(game: GameState, moment: Moment) -> None:
    """Resolve the effects held until ``moment``, and drop them whether they did anything or not.

    A held effect whose card has since left the table is a no-op, so one destroyed or banished
    earlier in the turn is not chased into the next.
    """
    held = _take_held(game, moment)
    if held:
        resolve_effects(game, held)


def discard_delayed(game: GameState, moment: Moment) -> None:
    """Forget the effects held until ``moment`` without resolving them.

    What a stretch of play owes when it ends before reaching ``moment``. An effect left held would
    resolve off the next stretch of play to reach that edge instead.
    """
    game.delayed = [entry for entry in game.delayed if entry[0] != moment]


def _take_held(game: GameState, moment: Moment) -> list[Effect]:
    """Remove and return the effects held until ``moment``."""
    held = [effect for held_until, effect in game.delayed if held_until == moment]
    discard_delayed(game, moment)
    return held

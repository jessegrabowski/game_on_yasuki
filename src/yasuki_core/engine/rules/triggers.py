import collections
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.game_events import (
    CardDiscarded,
    Destroyed,
    GameEvent,
)
from yasuki_core.engine.rules.vocabulary.decisions import CHOICE_PROMPTS
from yasuki_core.engine.rules.effects import (
    ApplyEffects,
    InterruptingEffect,
    Effect,
    Then,
)
from yasuki_core.engine.rules import state_based_actions
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.structure import Moment, RoundKind
from yasuki_core.engine.rules.vocabulary.modifiers import (
    ConditionalModifier,
    LobbyModifier,
    ProvinceModifier,
)
from yasuki_core.engine.table import ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import Counter

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

# event type -> printed_id -> triggers. Populated by the @on decorators below, on import; kept
# grouped by printed_id so collection is a lookup, not a rebuild per event.
_TRIGGERS: dict[type, dict[str, list[Trigger]]] = {}


def on(event_type: type, printed_id: str) -> Callable[[Trigger], Trigger]:
    """Register the decorated function as ``printed_id``'s trigger for ``event_type``."""

    def register(trigger: Trigger) -> Trigger:
        _TRIGGERS.setdefault(event_type, {}).setdefault(printed_id, []).append(trigger)
        return trigger

    return register


# event type -> triggers the rulebook itself takes, after every card's. A rulebook effect that
# follows an occurrence, such as the Honor loss after a dishonorable Personality dies, is a trigger
# with no card behind it, and it fires on the card the event names.
_RULEBOOK_TRIGGERS: dict[type, list[Trigger]] = {}


def rulebook_trigger(event_type: type) -> Callable[[Trigger], Trigger]:
    """Register the decorated function as a rulebook trigger for ``event_type``, fired after the
    card triggers for the same event with the card the event names as its context card."""

    def register(trigger: Trigger) -> Trigger:
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


def choice_resolver(key: str, *, prompt: str | None = None) -> Callable[[Resolver], Resolver]:
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
    """

    def register(resolver: Resolver) -> Resolver:
        if key in CHOICE_RESOLVERS:
            raise ValueError(f"{key} already has a choice resolver")
        CHOICE_RESOLVERS[key] = resolver
        if prompt is not None:
            CHOICE_PROMPTS[key] = prompt
        return resolver

    return register


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
    rulebook's, each on the card the event names."""
    firing = _card_triggers(game, event)
    firing.sort(key=_canonical_order)
    rulebook = _RULEBOOK_TRIGGERS.get(type(event))
    if rulebook:
        subject = _named_subject(game, event)
        if subject is not None:
            firing.extend((subject, trigger) for trigger in rulebook)
    return firing


def _card_triggers(game: GameState, event: GameEvent) -> list[tuple[L5RCard, Trigger]]:
    by_id = _TRIGGERS.get(type(event))
    if not by_id:
        return []
    firing = [
        (card, trigger)
        for card in game.table.battlefield.cards
        for trigger in by_id.get(card.printed_id, ())
    ]
    # A departed card answers only for its own leaving, and for nothing that happens after.
    departed = _departed_subject(game, event)
    if departed is not None:
        firing.extend((departed, trigger) for trigger in by_id.get(departed.printed_id, ()))
    return firing


def _named_subject(game: GameState, event: GameEvent) -> L5RCard | None:
    """The card ``event`` names, wherever it now is, or None for an event about no card."""
    card_id = getattr(event, "card_id", None)
    return None if card_id is None else game.table.cards_by_id.get(card_id)


def _canonical_order(pair: tuple[L5RCard, Trigger]) -> tuple[str, str]:
    card = pair[0]
    return (card.owner.name if card.owner else "", card.id)


def _advance(
    game: GameState,
    effects: tuple[Effect, ...],
    firing: list[tuple[L5RCard, Trigger]],
    event: GameEvent | None,
    queue: list[GameEvent],
    *,
    interruptible: bool,
) -> None:
    """Run the effect-and-trigger cascade to a fixpoint from an arbitrary resume point.

    One resumable worklist machine, in three repeating steps: apply the ``effects`` in hand (each
    committing at once, its derived events joining ``queue``), then fire the next trigger still
    ``firing`` for ``event``, whose effects become the next ``effects`` in hand, then pop the next
    event off ``queue`` and collect its triggers. An :class:`~.InterruptingEffect` among the effects
    pauses the machine: it records that effect's decision and stashes the exact remainder (the
    effects after it, the triggers not yet fired, the event, and the queue) as a
    :class:`~.ResumeCascade`, so :func:`~.resume_cascade` continues from precisely here once the
    seat answers.

    ``interruptible`` says the effects in hand are an action's own, the only ones an Interrupt may
    modify (ShE datasheet, Interrupt). Each is checked against the modifications the action's
    :class:`~.InterruptWindow` collected before it is applied, and resolves as what the Interrupt
    made of it. What a trigger returns is a trait's or the rulebook's, never the action's, so it
    is applied as returned, and a ``Then`` among the action's effects carries the flag to the
    deferred step."""
    resolved = 0
    firing = list(firing)
    while True:
        pending = list(effects)
        while pending:
            effect = pending.pop(0)
            if isinstance(effect, Then):
                _trace.append(f"    {effect.describe()}")
                game.stack.append(ApplyEffects(effect.effects, interruptible=interruptible))
                continue
            if interruptible and not isinstance(effect, InterruptingEffect):
                effect = _modified(game, effect)
            if isinstance(effect, InterruptingEffect) and effect.pauses(game):
                # Stash before asking for the request: the work stack is LIFO, and an effect whose
                # request queues its own work (a recruit queues its resolution) must have that work
                # run before the remainder of this cascade resumes.
                _stash(game, tuple(pending), firing, event, queue, interruptible)
                game.pending = effect.request(game)
                return
            _trace.append(f"    {effect.describe()}")
            queue.extend(apply_effect(game, effect))
            # What the effect produced goes next, ahead of the rest, so an attack's outcome resolves
            # where the attack stood and passes through the Interrupt step on its own.
            pending[:0] = effect.follow_on(game)
            _settle_state_based_actions(game, queue)
        effects = ()
        interruptible = False
        if firing:
            card, trigger = firing.pop(0)
            _trace.append(f"  {card.printed_id} ({card.id}) reacts")
            effects = tuple(trigger(TriggerContext(game, card, event)))
            continue
        if not queue:
            # The walk can be entered on a board something else already made illegal, and with
            # nothing to commit the per-effect check never runs. Judge it before returning.
            _settle_state_based_actions(game, queue)
            if not queue:
                return
        resolved += 1
        if resolved > _MAX_CASCADE:
            raise RuntimeError(
                f"trigger cascade did not converge after {_MAX_CASCADE} events:\n{_render_trace()}"
            )
        event = queue.pop(0)
        # Kept for the Response Step, which asks what the action it follows actually did. What an
        # Interrupt or a Response does inside its own round is its doing, not the action's.
        if game.round.kind not in (RoundKind.INTERRUPT, RoundKind.RESPONSE):
            game.action_events.append(event)
        _trace.append(type(event).__name__)
        firing = _collect(game, event)


def _modified(game: GameState, effect: Effect) -> Effect:
    """``effect`` as the Interrupts taken against the action make of it: every modification bound
    to it applies in the order the Interrupts were taken, and is spent."""
    original = effect
    for modification in list(game.modifications):
        if modification.answers(original):
            effect = modification.apply(game, effect)
            game.modifications.remove(modification)
    return effect


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
        _advance(game, (), [], None, queue, interruptible=False)


def _forget_ongoing_on_cards_off_the_table(game: GameState) -> None:
    """Drop ongoing records whose target has left the battlefield and the Provinces.

    A card that leaves play ceases to exist (CR), so nothing granted to it outlives the departure,
    ``PERMANENT`` included, whose permanence is against its *source* going away rather than its
    target. A Province card counts as still on the table. Repairing the Ruins raises a Holding's
    Gold Cost while it waits in one, and that has to survive being Recruited out of it.

    Forgotten rather than skipped when read: a card can return to a Province, and a record merely
    filtered out would come back attached to the card that replaced it. One laid on a condition, a
    Province slot or a player is kept whatever happens: none of those is a card that can leave the
    table.
    """
    if not game.ongoing:
        return
    on_table = {card.id for card in game.table.battlefield.cards}
    for key, zone in game.table.zones.items():
        if key.role is ZoneRole.PROVINCE:
            on_table.update(card.id for card in zone.cards)
    game.ongoing[:] = [
        record
        for record in game.ongoing
        if isinstance(record, ConditionalModifier | ProvinceModifier | LobbyModifier)
        or record.target_id in on_table
    ]


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
    """
    for _ in range(_MAX_CASCADE):
        _forget_ongoing_on_cards_off_the_table(game)
        demanded = state_based_actions.demanded(game)
        if not demanded:
            return
        for effect in demanded:
            _trace.append(f"    {effect.describe()} (state-based action)")
            queue.extend(apply_effect(game, effect))
    raise RuntimeError(
        f"state-based actions did not settle after {_MAX_CASCADE} rounds:\n{_render_trace()}"
    )


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
class ResumeCascade:
    """The exact remainder of an effect-and-trigger cascade a choice paused: the effects still to
    apply, then the ``(card_id, trigger)`` pairs still to fire for ``event``, then the events still
    queued behind them. The answered choice's own effects splice in ahead of these. It is ephemeral
    like the rest of the stack, since its effects and triggers are value-equal and stable
    module-level functions, so it rebuilds and compares equal under replay.

    Attributes
    ----------
    effects : tuple of Effect
        The effects still to apply for the paused trigger, after the one that raised the choice.
    firing : tuple of (str, callable)
        The card id and trigger of each subscriber still to fire for ``event``.
    event : GameEvent or None
        The event those triggers are firing for, or None when the pause held only loose effects.
    queue : tuple of GameEvent
        The events still waiting behind ``event`` in the paused worklist.
    interruptible : bool, optional
        Whether the effects still to apply are an action's own, open to the Interrupt step.
        Default False.
    """

    effects: tuple[Effect, ...]
    firing: tuple[tuple[str, Trigger], ...]
    event: GameEvent | None
    queue: tuple[GameEvent, ...]
    interruptible: bool = False

    def resume(self, game: GameState) -> None:
        # An interrupting effect whose answer produces no effects of its own, a payment, say, leaves
        # its stash here for the generic drain. A Choose goes through `resume_paused_cascade`, which
        # splices the resolver's effects in.
        resume_cascade(game, self, [])


def _stash(
    game: GameState,
    effects: tuple[Effect, ...],
    firing: list[tuple[L5RCard, Trigger]],
    event: GameEvent | None,
    queue: list[GameEvent],
    interruptible: bool,
) -> None:
    remaining = tuple((card.id, trigger) for card, trigger in firing)
    game.stack.append(ResumeCascade(effects, remaining, event, tuple(queue), interruptible))


def resume_cascade(game: GameState, item: ResumeCascade, produced: list[Effect]) -> None:
    """Continue a cascade an interrupting effect paused, splicing ``produced`` (the effects the
    answer produced) in where that effect stood, ahead of the effects, triggers, and events the
    pause stashed. Triggers whose card has since left play are dropped."""
    firing = [
        (game.table.cards_by_id[card_id], trigger)
        for card_id, trigger in item.firing
        if card_id in game.table.cards_by_id
    ]
    _advance(
        game,
        tuple(produced) + item.effects,
        firing,
        item.event,
        list(item.queue),
        interruptible=item.interruptible,
    )


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
    """

    effects: tuple[Effect, ...]

    def resume(self, game: GameState) -> None:
        _advance(game, self.effects, [], None, [], interruptible=True)


def resume_paused_cascade(game: GameState, produced: list[Effect]) -> None:
    """Pop the cascade the answered choice paused and continue it with ``produced`` spliced in.

    The stash is always the top of the stack: a choice pauses the walk the moment it is raised, and
    nothing pushes between the pause and the answer. Raise ``RuntimeError`` if it is not there.
    """
    item = game.stack.pop()
    if not isinstance(item, ResumeCascade):
        raise RuntimeError("a card choice resumed without its stashed cascade")
    resume_cascade(game, item, produced)


def fire(game: GameState, event: GameEvent) -> None:
    """Resolve ``event`` and the cascade it triggers, running the worklist to a fixpoint.

    The single-event case of :func:`~.fire_all`. Occurrences that happen at the same instant go
    through that one together; firing them one after another imposes an order the rules do not.

    Raise ``RuntimeError`` if a decision is pending.
    """
    _refuse_mid_decision(game, "fire")
    _advance(game, (), [], None, [event], interruptible=False)


def fire_all(game: GameState, events: Sequence[GameEvent]) -> None:
    """Resolve ``events`` as one cascade, for occurrences that happen at the same instant.

    Firing them one at a time is not the same thing: a trigger that pauses for a decision leaves
    the machine stopped, and the next call would start a second cascade on top of the pending
    request and overwrite it.

    Raise ``RuntimeError`` if a decision is pending.
    """
    _refuse_mid_decision(game, "fire_all")
    _advance(game, (), [], None, list(events), interruptible=False)


def resolve_effects(game: GameState, effects: list[Effect]) -> None:
    """Apply ``effects`` and run the derived-event cascade the same way :func:`~.fire` does, so a
    triggered reaction to those effects still resolves. The effects are not an action's own, so
    none is held at the Interrupt step: a cost, a rulebook procedure's effects, a trait's, and an
    Interrupt's own effects all come through here.

    Raise ``RuntimeError`` if a decision is pending.
    """
    _refuse_mid_decision(game, "resolve_effects")
    _advance(game, tuple(effects), [], None, [], interruptible=False)


def resolve_action_effects(game: GameState, effects: list[Effect]) -> None:
    """Apply ``effects`` as an action's own, which is what step E of the Action Sequence hands
    over. The first effects an action hands over are held beneath an Interrupt round first (CR,
    Action Sequence step D), when any seat holds an Interrupt to take, and every effect resolves
    as the Interrupts taken there make of it. What the action defers behind them through a
    ``Then`` opens no second round. The derived-event cascade runs as in
    :func:`~.resolve_effects`.

    Raise ``RuntimeError`` if a decision is pending.
    """
    # Imported where it is used: the Interrupt step reads the hands and the round, and the module
    # that does so imports this one.
    from yasuki_core.engine.rules.interrupts import open_interrupt_window

    _refuse_mid_decision(game, "resolve_action_effects")
    if game.interrupts_offered:
        _advance(game, tuple(effects), [], None, [], interruptible=True)
        return
    game.interrupts_offered = True
    held = HeldAction(tuple(effects))
    game.stack.append(held)
    if not open_interrupt_window(game):
        game.stack.pop()
        held.resume(game)


def action_did(game: GameState, kind: type[GameEvent]) -> tuple[GameEvent, ...]:
    """Every event of ``kind`` the action now resolving has produced, in the order it happened.

    What a Response reads to know what it is answering: "discarded a Fate card" and "Recruits this
    Holding" are facts about the action rather than about the board it leaves behind.
    """
    return tuple(event for event in game.action_events if isinstance(event, kind))


def resolve_delayed(game: GameState, moment: Moment) -> None:
    """Resolve the effects held until ``moment``, and drop them whether they did anything or not.

    A held effect whose card has since left the table is a no-op, so one destroyed or banished
    earlier in the turn is not chased into the next.
    """
    held = [effect for held_until, effect in game.delayed if held_until == moment]
    if not held:
        return
    game.delayed = [entry for entry in game.delayed if entry[0] != moment]
    resolve_effects(game, held)

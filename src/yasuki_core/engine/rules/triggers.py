import collections
from collections.abc import Callable
from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.events import (
    GameEvent,
)
from yasuki_core.engine.rules.decisions import CHOICE_PROMPTS
from yasuki_core.engine.rules.effects import (
    InterruptingEffect,
    Effect,
)
from yasuki_core.engine.rules import state_rules
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.economy import effective_keywords
from yasuki_core.engine.rules.work import ResumeCascade
from yasuki_core.engine.table import ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import Counter, SINCERITY
from yasuki_core.game_pieces.prints import HoldingPrint

# A sanity bound on both fixpoint walks: a converging cascade drains in a handful of events, and
# the state rules settle in a handful of rounds, so far more than this means a trigger re-emits an
# event that re-fires it or a rule demands what does not satisfy it — a bug, raised loudly.
_MAX_CASCADE = 1000

# The tail of the current walk, kept only to describe a cascade that fails to converge. Module-level
# and bounded rather than carried on GameState: the history is derived (replay regenerates it), and
# GameState compares by field, so storing it there would drag traces into every replay-equality
# assertion. A deque of this size holds several cycles of any loop a human would need to read.
_TRACE_LIMIT = 60
_trace: collections.deque[str] = collections.deque(maxlen=_TRACE_LIMIT)

# The keyword whose cards accrue and receive seeded Sincerity tokens.
SINCERITY_KEYWORD = "Sincerity"


@dataclass(frozen=True, slots=True)
class TriggerContext:
    """What a trigger reads: the live game, the card whose trigger is firing, and the event."""

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


# A choice resolver turns the ids a Choose collected into the effects the choice produces, given the
# seat that answered. Keyed by a string so a paused ChooseCards names its resolver, keeping the
# pending decision replay-stable (a stored closure would not rebuild to an equal object).
Resolver = Callable[[GameState, str | None, tuple[str, ...], PlayerId], list[Effect]]
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
    """Whether ``card`` already holds ``cap`` or more of ``counter`` — a shared trigger guard."""
    return card.counters.get(counter.key, 0) >= cap


def caused_by(ctx: TriggerContext, seat: PlayerId) -> bool:
    """Whether ``seat``'s own action caused the event — the "if the action was yours" guard. Reads
    the event's ``cause``; only meaningful for events that carry one. False when the rulebook caused
    it, since no seat did."""
    return ctx.event.cause is seat


def once_per_turn(game: GameState, card: L5RCard, tag: str) -> bool:
    """Claim a once-per-turn use for ``card``'s ``tag``: True the first time this turn, then False.
    Turn-scoped, so it resets each turn without clearing ``GameState.once_per``."""
    return game.use_once(f"{card.id}:{tag}:t{game.turn}")


def apply_effect(game: GameState, effect: Effect) -> list[GameEvent]:
    """Commit one effect and return the events it raises, for the fixpoint walk to drain. This is
    the single mutation boundary; triggers themselves never mutate."""
    return effect.perform(game)


def _collect(game: GameState, event: GameEvent) -> list[tuple[L5RCard, Trigger]]:
    by_id = _TRIGGERS.get(type(event))
    if not by_id:
        return []
    return [
        (card, trigger)
        for card in game.table.battlefield.cards
        for trigger in by_id.get(card.printed_id, ())
    ]


def _canonical_order(pair: tuple[L5RCard, Trigger]) -> tuple[str, str]:
    card = pair[0]
    return (card.owner.name if card.owner else "", card.id)


def _advance(
    game: GameState,
    effects: tuple[Effect, ...],
    firing: list[tuple[L5RCard, Trigger]],
    event: GameEvent | None,
    queue: list[GameEvent],
) -> None:
    """Run the effect-and-trigger cascade to a fixpoint from an arbitrary resume point.

    One resumable worklist machine, in three repeating steps: apply the ``effects`` in hand (each
    committing at once, its derived events joining ``queue``); then fire the next trigger still
    ``firing`` for ``event``, whose effects become the next ``effects`` in hand; then pop the next
    event off ``queue`` and collect its triggers. An :class:`InterruptingEffect` among the effects
    pauses the machine: it records that effect's decision and stashes the exact remainder (the
    effects after it, the triggers not yet fired, the event, and the queue) as a
    :class:`ResumeCascade`, so :func:`resume_cascade` continues from precisely here once the seat
    answers."""
    resolved = 0
    firing = list(firing)
    while True:
        for index, effect in enumerate(effects):
            if isinstance(effect, InterruptingEffect):
                # Stash before asking for the request: the work stack is LIFO, and an effect whose
                # request queues its own work (a recruit queues its resolution) must have that work
                # run before the remainder of this cascade resumes.
                _stash(game, tuple(effects[index + 1 :]), firing, event, queue)
                game.pending = effect.request(game)
                return
            _trace.append(f"    {effect.describe()}")
            queue.extend(apply_effect(game, effect))
            _settle_state_rules(game, queue)
        effects = ()
        if firing:
            card, trigger = firing.pop(0)
            _trace.append(f"  {card.printed_id} ({card.id}) reacts")
            effects = tuple(trigger(TriggerContext(game, card, event)))
            continue
        if not queue:
            # The walk can be entered on a board something else already made illegal, and with
            # nothing to commit the per-effect check never runs. Judge it before returning.
            _settle_state_rules(game, queue)
            if not queue:
                return
        resolved += 1
        if resolved > _MAX_CASCADE:
            raise RuntimeError(
                f"trigger cascade did not converge after {_MAX_CASCADE} events:\n{_render_trace()}"
            )
        event = queue.pop(0)
        _trace.append(type(event).__name__)
        firing = _collect(game, event)
        firing.sort(key=_canonical_order)


def enforce_state_rules(game: GameState) -> None:
    """Satisfy the state-based rules against the board as it stands, resolving what that raises.

    For the board changes the cascade does not make — a card placed on the battlefield by ``flow``,
    a modifier expiring at a turn boundary. The walk enforces the rules after each effect it
    commits; this is how a caller that mutated the board directly gets the same guarantee.
    """
    queue: list[GameEvent] = []
    _settle_state_rules(game, queue)
    if queue:
        _advance(game, (), [], None, queue)


def _settle_state_rules(game: GameState, queue: list[GameEvent]) -> None:
    """Satisfy every state-based rule before anything else happens, queueing what the enforcement
    raises.

    These rules are conditions the board must satisfy at all times rather than reactions to an
    event, so the ordering is the rule: enforced after each committed effect rather than once the
    cascade settles, an illegal board never survives long enough for anything to read it. Nothing
    commits behind the change that broke a condition, no trigger fires on the broken state, and the
    walk cannot pause for a decision while it stands, because the pause is tested before an effect
    applies and every applied effect has already been judged.

    Enforcement runs to its own fixpoint: satisfying one condition can break another, and the CR's
    conditions chain that way by design — a destroyed card can orphan what was attached to it, and
    a seat losing its last Province loses the game.
    """
    for _ in range(_MAX_CASCADE):
        demanded = state_rules.demanded(game)
        if not demanded:
            return
        for effect in demanded:
            _trace.append(f"    {effect.describe()} (state rule)")
            queue.extend(apply_effect(game, effect))
    raise RuntimeError(
        f"state rules did not settle after {_MAX_CASCADE} rounds:\n{_render_trace()}"
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


def _stash(
    game: GameState,
    effects: tuple[Effect, ...],
    firing: list[tuple[L5RCard, Trigger]],
    event: GameEvent | None,
    queue: list[GameEvent],
) -> None:
    remaining = tuple((card.id, trigger) for card, trigger in firing)
    game.stack.append(ResumeCascade(effects, remaining, event, tuple(queue)))


def resume_cascade(game: GameState, item: ResumeCascade, produced: list[Effect]) -> None:
    """Continue a cascade an interrupting effect paused, splicing ``produced`` (the effects the
    answer produced) in where that effect stood, ahead of the effects, triggers, and events the
    pause stashed. Triggers whose card has since left play are dropped."""
    firing = [
        (game.table.cards_by_id[card_id], trigger)
        for card_id, trigger in item.firing
        if card_id in game.table.cards_by_id
    ]
    _advance(game, tuple(produced) + item.effects, firing, item.event, list(item.queue))


def fire(game: GameState, event: GameEvent) -> None:
    """Resolve ``event`` and the cascade it triggers, running the worklist to a fixpoint."""
    _advance(game, (), [], None, [event])


def resolve_effects(game: GameState, effects: list[Effect]) -> None:
    """Apply ``effects`` — an ability's or a choice resolver's output — and run the derived-event
    cascade the same way :func:`fire` does, so a triggered reaction to those effects still resolves."""
    _advance(game, tuple(effects), [], None, [])


def sincerity_seed_targets(game: GameState, seat: PlayerId) -> list[str]:
    """The seat's face-up Sincerity cards still in a Province with no Sincerity tokens — the legal
    recipients of a seeded Sincerity token."""
    return [
        card.id
        for key, zone in game.table.zones.items()
        if key.owner is seat and key.role is ZoneRole.PROVINCE
        for card in zone.cards
        if card.face_up
        and SINCERITY_KEYWORD in effective_keywords(game, card)
        and card.counters.get(SINCERITY.key, 0) == 0
    ]


def province_holdings(game: GameState, seat: PlayerId) -> list[str]:
    """The seat's face-up Holdings still in a Province — the recruitable targets of a targeted
    recruit ability."""
    return [
        card.id
        for key, zone in game.table.zones.items()
        if key.owner is seat and key.role is ZoneRole.PROVINCE
        for card in zone.cards
        if card.face_up and isinstance(card.printed, HoldingPrint)
    ]

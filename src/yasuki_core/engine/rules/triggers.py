from collections.abc import Callable
from dataclasses import dataclass

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.events import CardDiscarded, CounterGained, GameEvent, TurnStarted
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import Counter, WEALTH
from yasuki_core.game_pieces.dynasty import DynastyHolding

# A sanity bound on the fixpoint walk: a converging cascade drains in a handful of events, so far
# more than this means a trigger re-emits an event that re-fires it — a card-logic bug, raised loudly.
_MAX_CASCADE = 1000


@dataclass(frozen=True, slots=True)
class AdjustCounter:
    """Effect: add ``delta`` to a counter on a card (floored at zero by the card). A grant is a
    positive delta, a removal negative. The rules-side twin of the sandbox ``AdjustCounter`` intent,
    applied through :func:`apply_effect` rather than ``apply_intent``."""

    card_id: str
    counter: Counter
    delta: int


@dataclass(frozen=True, slots=True)
class DrawCard:
    """Effect: ``seat`` draws a card from its fate deck."""

    seat: PlayerId


Effect = AdjustCounter | DrawCard


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


def at_cap(card: L5RCard, counter: Counter, cap: int) -> bool:
    """Whether ``card`` already holds ``cap`` or more of ``counter`` — a shared trigger guard."""
    return card.counters.get(counter.key, 0) >= cap


def caused_by(ctx: TriggerContext, seat: PlayerId) -> bool:
    """Whether ``seat``'s own action caused the event — the "if the action was yours" guard. Reads
    the event's ``by_seat``; only meaningful for events that carry one."""
    return ctx.event.by_seat is seat


def once_per_turn(game: GameState, card: L5RCard, tag: str) -> bool:
    """Claim a once-per-turn use for ``card``'s ``tag``: True the first time this turn, then False.
    Turn-scoped, so it resets each turn without clearing ``GameState.once_per``."""
    return game.use_once(f"{card.id}:{tag}:t{game.turn}")


def apply_effect(game: GameState, effect: Effect) -> list[GameEvent]:
    """Commit one effect and return the events it raises, for the fixpoint walk to drain. This is the
    single mutation boundary; triggers themselves never mutate."""
    match effect:
        case AdjustCounter(card_id=card_id, counter=counter, delta=delta):
            card = game.table.cards_by_id.get(card_id)
            if card is None:
                return []
            before = card.counters.get(counter.key, 0)
            card.adjust_counter(counter.key, delta)
            gained = card.counters.get(counter.key, 0) - before
            if gained > 0:
                return [CounterGained(card_id, counter, gained)]
        case DrawCard(seat=seat):
            ops.draw_to_hand(game.table, seat)
    return []


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


def fire(game: GameState, event: GameEvent) -> None:
    """Resolve ``event`` and the cascade it triggers, draining a worklist to a fixpoint. Collect the
    cards whose trigger subscribes to the event, resolve each in a canonical order (controller, then
    id), and apply the effects they return — whose own derived events re-enter the worklist."""
    queue: list[GameEvent] = [event]
    resolved = 0
    while queue:
        resolved += 1
        if resolved > _MAX_CASCADE:
            raise RuntimeError(f"trigger cascade did not converge after {_MAX_CASCADE} events")
        current = queue.pop(0)
        firing = _collect(game, current)
        firing.sort(key=_canonical_order)
        for card, trigger in firing:
            for effect in trigger(TriggerContext(game, card, current)):
                queue.extend(apply_effect(game, effect))


# Per-card triggers, registered on import of this module (as effects.py holds its gold handlers).


@on(TurnStarted, "rice_farm")
def _rice_farm(ctx: TriggerContext) -> list[Effect]:
    """After your turn begins, give this Holding a +1GP Wealth token (max four)."""
    if ctx.card.owner is not ctx.event.seat or at_cap(ctx.card, WEALTH, 4):
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


@on(CardDiscarded, "caravansary")
def _caravansary(ctx: TriggerContext) -> list[Effect]:
    """If your action discarded a Fate card, give this Holding a +1GP Wealth token (max three)."""
    if not caused_by(ctx, ctx.card.owner) or ctx.event.side is not Side.FATE:
        return []
    if at_cap(ctx.card, WEALTH, 3):
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


@on(CounterGained, "shosuro_aoki_yoritomo_kayoko_experienced")
def _shosuro_aoki(ctx: TriggerContext) -> list[Effect]:
    """After your Holding gains any Wealth tokens, once per turn, draw a card."""
    if ctx.event.counter is not WEALTH:
        return []
    gainer = ctx.game.table.cards_by_id.get(ctx.event.card_id)
    if not isinstance(gainer, DynastyHolding) or gainer.owner is not ctx.card.owner:
        return []
    if not once_per_turn(ctx.game, ctx.card, "aoki_draw"):
        return []
    return [DrawCard(ctx.card.owner)]

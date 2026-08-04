from collections.abc import Callable
from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.events import (
    CardDiscarded,
    CounterGained,
    Destroyed,
    EnteredPlay,
    GameEvent,
    TurnStarted,
)
from yasuki_core.engine.rules.effects import (
    InterruptingEffect,
    AdjustCounter,
    Choose,
    Destroy,
    DrawCard,
    Effect,
    GainGold,
    IgnoreHonorRequirements,
    Straighten,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.work import ResumeCascade
from yasuki_core.engine.table import ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import Counter, SINCERITY, WEALTH
from yasuki_core.game_pieces.dynasty import DynastyHolding

# A sanity bound on the fixpoint walk: a converging cascade drains in a handful of events, so far
# more than this means a trigger re-emits an event that re-fires it — a card-logic bug, raised loudly.
_MAX_CASCADE = 1000

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


# A choice resolver turns the ids a Choose collected into the effects the choice produces. Keyed by a
# string so a paused ChooseCards names its resolver, keeping the pending decision replay-stable (a
# stored closure would not rebuild to an equal object).
Resolver = Callable[[GameState, str, tuple[str, ...]], list[Effect]]
CHOICE_RESOLVERS: dict[str, Resolver] = {}


def choice_resolver(key: str) -> Callable[[Resolver], Resolver]:
    """Register the decorated function as the choice resolver named ``key``."""

    def register(resolver: Resolver) -> Resolver:
        if key in CHOICE_RESOLVERS:
            raise ValueError(f"{key} already has a choice resolver")
        CHOICE_RESOLVERS[key] = resolver
        return resolver

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
            queue.extend(apply_effect(game, effect))
        effects = ()
        if firing:
            card, trigger = firing.pop(0)
            effects = tuple(trigger(TriggerContext(game, card, event)))
            continue
        if not queue:
            return
        resolved += 1
        if resolved > _MAX_CASCADE:
            raise RuntimeError(f"trigger cascade did not converge after {_MAX_CASCADE} events")
        event = queue.pop(0)
        firing = _collect(game, event)
        firing.sort(key=_canonical_order)


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


@on(EnteredPlay, "rural_market")
def _rural_market_enters_play(ctx: TriggerContext) -> list[Effect]:
    """After this Holding enters play, give it a +1GP Wealth token."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


@on(Destroyed, "rural_market")
def _rural_market_farm_destroyed(ctx: TriggerContext) -> list[Effect]:
    """After your Farm is destroyed, give this Holding a +1GP Wealth token."""
    destroyed = ctx.game.table.cards_by_id.get(ctx.event.card_id)
    if destroyed is None or destroyed.owner is not ctx.card.owner:
        return []
    if "Farm" not in destroyed.keywords:
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


@on(EnteredPlay, "wheat_farm")
def _wheat_farm(ctx: TriggerContext) -> list[Effect]:
    """After this Holding enters play, let its controller give zero to two other Farms they control a
    +1GP Wealth token."""
    if ctx.event.card_id != ctx.card.id:
        return []
    others = tuple(
        card.id
        for card in ctx.game.table.battlefield.cards
        if card.owner is ctx.card.owner
        and card is not ctx.card
        and isinstance(card, DynastyHolding)
        and "Farm" in card.keywords
    )
    if not others:
        return []
    return [Choose(ctx.card.owner, others, 0, min(2, len(others)), "wheat_farm", ctx.card.id)]


@choice_resolver("wheat_farm")
def _wheat_farm_grant(game: GameState, source_id: str, chosen: tuple[str, ...]) -> list[Effect]:
    return [AdjustCounter(card_id, WEALTH, 1) for card_id in chosen]


@on(EnteredPlay, "pawnbroker")
def _pawnbroker(ctx: TriggerContext) -> list[Effect]:
    """After this Holding enters play, turn each Sincerity token it accrued into a +1GP Wealth
    token."""
    if ctx.event.card_id != ctx.card.id:
        return []
    sincerity = ctx.card.counters.get(SINCERITY.key, 0)
    if sincerity == 0:
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, sincerity)]


@on(EnteredPlay, "sapphire_mine")
def _sapphire_mine(ctx: TriggerContext) -> list[Effect]:
    """Sincerity: after this Holding enters play, if it accrued two or more Sincerity tokens, give it
    a +1GP Wealth token."""
    if ctx.event.card_id != ctx.card.id:
        return []
    if ctx.card.counters.get(SINCERITY.key, 0) < 2:
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


@on(EnteredPlay, "mishime_sensei")
def _mishime_sensei_enters_play(ctx: TriggerContext) -> list[Effect]:
    """Mishime Sensei: grant its controller the ignore-Honor-Requirements waiver as it enters
    play."""
    if ctx.event.card_id != ctx.card.id or ctx.card.owner is None:
        return []
    return [IgnoreHonorRequirements(ctx.card.owner)]


@on(EnteredPlay, "the_kurai_district_court")
def _kurai_district_court(ctx: TriggerContext) -> list[Effect]:
    """After this Holding enters play, produce one Gold for each Sincerity token it accrued."""
    if ctx.event.card_id != ctx.card.id:
        return []
    sincerity = ctx.card.counters.get(SINCERITY.key, 0)
    if sincerity == 0:
        return []
    return [GainGold(ctx.card.owner, sincerity)]


def sincerity_seed_targets(game: GameState, seat: PlayerId) -> list[str]:
    """The seat's face-up Sincerity cards still in a Province with no Sincerity tokens — the legal
    recipients of a seeded Sincerity token."""
    return [
        card.id
        for key, zone in game.table.zones.items()
        if key.owner is seat and key.role is ZoneRole.PROVINCE
        for card in zone.cards
        if card.face_up
        and SINCERITY_KEYWORD in card.keywords
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
        if card.face_up and isinstance(card, DynastyHolding)
    ]


@choice_resolver("modest_farm_straighten")
def _modest_farm_straighten(
    game: GameState, source_id: str, chosen: tuple[str, ...]
) -> list[Effect]:
    # source_id is the recruited target; chosen holds Modest Farm's id when its controller sacrifices
    # it to straighten the target.
    if not chosen:
        return []
    return [Destroy(chosen[0]), Straighten(source_id)]


@on(EnteredPlay, "training_court")
def _training_court(ctx: TriggerContext) -> list[Effect]:
    """Political Tireless Response: after Training Court enters play, seed a Sincerity token onto one
    of its controller's token-less Sincerity cards still in a Province."""
    if ctx.event.card_id != ctx.card.id:
        return []
    targets = tuple(sincerity_seed_targets(ctx.game, ctx.card.owner))
    if not targets:
        return []
    return [Choose(ctx.card.owner, targets, 1, 1, "sincerity_seed", ctx.card.id)]


@choice_resolver("sincerity_seed")
def _sincerity_seed(game: GameState, source_id: str, chosen: tuple[str, ...]) -> list[Effect]:
    return [AdjustCounter(card_id, SINCERITY, 1) for card_id in chosen]

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.costs import can_pay, priced_cost
from yasuki_core.engine.rules.abilities.activation import ResolveAbility
from yasuki_core.engine.rules.abilities.model import CardLocation, Interrupt, InterruptLimit
from yasuki_core.engine.rules.abilities.registry import ability_for, interrupt_for, interrupts_for
from yasuki_core.engine.rules.abilities.strategy import play_strategy_with
from yasuki_core.engine.rules.effects import AttackEffect, Effect, SpendOncePerTurn, Then
from yasuki_core.engine.rules.gold.discounts import discounted_gold_cost
from yasuki_core.engine.rules.gold.producers import reachable_gold
from yasuki_core.engine.rules.legality import (
    legal_targets,
    location_permits,
    permitted_timings_in,
    seat_cards,
)
from yasuki_core.engine.rules.state import GameState, used_this_turn
from yasuki_core.engine.rules.action_record import action_is_unstoppable
from yasuki_core.engine.rules.turn.structure import (
    INTERRUPT_TIMINGS,
    ActionRound,
    RoundKind,
    RoundTimings,
)
from yasuki_core.engine.rules.vocabulary.actions import Action, ActionTiming, PlayInterrupt
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseInterruptEffect,
    ChooseInterruptTarget,
    DecisionResponse,
)
from yasuki_core.game_pieces.cards import L5RCard


def forecast(game: GameState, effects: tuple[Effect, ...]) -> tuple[Effect, ...]:
    """What an action handing ``effects`` to step E is about to do, as the Interrupt step offers
    it: the effects in order, a ``Then``'s contents where it stands, an ability's effects behind
    the :class:`~.ResolveAbility` that targets them, and an attack's outcome behind the attack
    when it reaches on the board as it stands. An effect that is nothing to interrupt, an Honor
    change of zero or a question the action asks, is left out, and what a choice resolver
    produces later is not foreseeable and is not offered."""
    seen: list[Effect] = []
    for effect in effects:
        if isinstance(effect, Then):
            seen.extend(forecast(game, effect.effects))
            continue
        if effect.is_interruptible(game):
            seen.append(effect)
        stands = as_modified(game, effect)
        if isinstance(stands, ResolveAbility | AttackEffect):
            seen.extend(forecast(game, stands.follow_on(game)))
    return tuple(seen)


def as_modified(game: GameState, effect: Effect) -> Effect:
    """``effect`` as the Interrupts already taken against the action will have it resolve, read
    without spending them: what the step forecasts behind a negated attack is nothing."""
    for modification in game.modifications:
        if modification.answers(effect):
            effect = modification.apply(game, effect)
    return effect


@dataclass(frozen=True, slots=True)
class Replacement:
    """A card Interrupt's answer to one effect of the action, bound to the effect as the forecast
    showed it. What resolves instead is asked of the card's Interrupt as the effect comes up,
    against the effect as earlier Interrupts leave it, so a negation after a Courage adjustment
    negates the adjusted Fear. The Interrupt's own effects resolved when it was taken.

    Attributes
    ----------
    bound : Effect
        The action's effect, as first handed to step E, that the Interrupt answered.
    card_id : str
        The card whose Interrupt was taken.
    target_id : str, optional
        The target the Interrupt was taken against, for one that takes a target. Default None.
    replacement : Effect, optional
        What resolves instead, settled when the Interrupt was taken, for a replacement whose
        contents read the board: a substituted :class:`~.ResolveAbility` is built against its new
        target then, so the forecast and the resolution read one object. Used while the effect
        still stands as bound. Default None, asked of the card as the effect comes up.
    interrupt_key : str, optional
        The key of the Interrupt taken, for one a keyword conferred. Default None, the card's
        printed Interrupt.
    """

    bound: Effect
    card_id: str
    target_id: str | None = None
    replacement: Effect | None = None
    interrupt_key: str | None = None

    def answers(self, effect: Effect) -> bool:
        return effect == self.bound

    def apply(self, game: GameState, effect: Effect) -> Effect:
        if self.replacement is not None and effect == self.bound:
            return self.replacement
        card = game.table.cards_by_id[self.card_id]
        interrupt = interrupt_for(card, self.interrupt_key)
        if interrupt is None:
            raise RuntimeError(f"{self.card_id} has no Interrupt {self.interrupt_key!r} to apply")
        if self.target_id is None:
            return interrupt.interrupt(game, card, effect).replacement
        target = game.table.cards_by_id[self.target_id]
        return interrupt.interrupt(game, card, effect, target).replacement


def _unique(effects: Iterable[Effect]) -> list[Effect]:
    """``effects`` with later duplicates dropped: two alike in every field are one answer, since a
    modification binds to the effect by value and the first to resolve takes it."""
    return list(dict.fromkeys(effects))


# The once-per-turn tag an Interrupt taken from play is claimed under (CR, Using Abilities 0.3).
INTERRUPT_TAG = "interrupt"


def card_interrupts_for(
    game: GameState, seat: PlayerId, foreseen: tuple[Effect, ...]
) -> list[tuple[L5RCard, Interrupt, CardLocation]]:
    """The Interrupts ``seat`` could take against an action about to do ``foreseen``, each with
    the card offering it and where it is taken from. The Rule of Presence is the round's to apply,
    through :func:`~yasuki_core.engine.rules.legality.permitted_timings_in`, so a seat with no
    unit at the battle is never asked here.

    Each is offered when it answers one of the effects, within its limit. A card's own Interrupt
    in hand is a Strategy, offered when the seat can reach its Gold Cost. Anything else is offered
    when the seat can pay the Interrupt's cost, and a card in play only while unbowed and within
    the Rules of Location.
    """
    return [
        (card, interrupt, location)
        for location, card in seat_cards(game, seat)
        for interrupt in interrupts_for(game, card)
        if location in interrupt.located_at
        and _within_limit(game, seat, card, interrupt)
        and answered_by(game, card, interrupt, foreseen)
        and _affordable(game, seat, card, interrupt, location)
    ]


def _within_limit(game: GameState, seat: PlayerId, card: L5RCard, interrupt: Interrupt) -> bool:
    match interrupt.limit:
        case InterruptLimit.ONCE_PER_TURN:
            once = ruleset.ACTIVE.abilities_once_per_turn
            return not (once and used_this_turn(game, card, INTERRUPT_TAG))
        case InterruptLimit.ONCE_PER_ACTION:
            return (_action_tag(card, interrupt), seat) not in game.interrupts_taken
        case InterruptLimit.UNLIMITED:
            return True


def _action_tag(card: L5RCard, interrupt: Interrupt) -> str:
    """What a once-per-action Interrupt is recorded under in ``interrupts_taken``: its key, so a
    seat's second card carrying the same keyword is held to the same limit."""
    return interrupt.key or card.id


def _affordable(
    game: GameState, seat: PlayerId, card: L5RCard, interrupt: Interrupt, location: CardLocation
) -> bool:
    if _plays_card(interrupt, location):
        purchase = interrupt.purchase(game, card, plays_card=True)
        return discounted_gold_cost(game, purchase) <= reachable_gold(game, seat, card)
    if location is not CardLocation.HAND and (card.bowed or not location_permits(game, card)):
        return False
    return can_pay(game, card, interrupt.cost)


def _plays_card(interrupt: Interrupt, location: CardLocation) -> bool:
    """Whether taking ``interrupt`` from ``location`` plays the card: a card's own Interrupt in
    hand does, and one the rulebook confers pays its own cost instead (CR, Kharmic)."""
    return location is CardLocation.HAND and not interrupt.from_rulebook


def answered_by(
    game: GameState, card: L5RCard, interrupt: Interrupt, foreseen: tuple[Effect, ...]
) -> list[Effect]:
    """Those of ``foreseen`` that ``card``'s ``interrupt`` may be taken against: of its type as
    the Interrupts already taken leave it, within its ``applies``, and with a target to name where
    it takes one."""
    return _unique(
        effect
        for effect in foreseen
        if isinstance(as_modified(game, effect), interrupt.answers)
        and interrupt.applies(game, card, effect)
        and (interrupt.targets is None or interrupt.targets(game, card, effect))
    )


def legal_substitutes(
    game: GameState, targeting: ResolveAbility, candidate_ids: list[str]
) -> tuple[str, ...]:
    """Those of ``candidate_ids`` the ability about to resolve could target in place of its chosen
    target: legal targets of the ability that are not the one already chosen (CR, Substitution and
    Targets). What an Interrupt reading "the action targets X instead, if legal" offers."""
    source = game.table.cards_by_id[targeting.card_id]
    ability = ability_for(game, source, targeting.ability_key)
    if ability is None:
        return ()
    legal = set(legal_targets(game, source, ability))
    return tuple(
        candidate
        for candidate in candidate_ids
        if candidate in legal and candidate != targeting.target_id
    )


def held_action(game: GameState) -> triggers.HeldAction:
    """The action held at the Interrupt step, from the stack. Raise ``RuntimeError`` if none is."""
    for item in reversed(game.stack):
        if isinstance(item, triggers.HeldAction):
            return item
    raise RuntimeError("no action is held at the Interrupt step")


def foreseen_now(game: GameState) -> tuple[Effect, ...]:
    """The forecast of the action held at the Interrupt step."""
    return forecast(game, held_action(game).effects)


def interrupt_actions(game: GameState, seat: PlayerId) -> list[Action]:
    """The Interrupts ``seat`` may take against the action held at the Interrupt step, as a
    :class:`~.PlayInterrupt` per card and Interrupt that answers the forecast."""
    return [
        PlayInterrupt(card.id, interrupt.key)
        for card, interrupt, _ in card_interrupts_for(game, seat, foreseen_now(game))
    ]


def open_interrupt_window(game: GameState) -> bool:
    """Open the Interrupt step over the action just held, as a round of its own, and report
    whether it opened (CR, Action Sequence step D; ShE datasheet, Interrupt).

    Only when a seat entitled to act holds an Interrupt to take: a step nobody could act in is a
    pass nobody needs to be asked for. Nobody during a Response Step, since a Response is not
    interruptible. The active player acts first. During the acting seat's Unstoppable action no
    other seat is entitled at all (ShE datasheet, Unstoppable).
    """
    if game.round.kind is RoundKind.RESPONSE:
        return False
    step = ActionRound(
        timings=_window_timings(game), priority=game.active, kind=RoundKind.INTERRUPT
    )
    order = [game.active, *(seat for seat in game.table.seats if seat is not game.active)]
    first = next(
        (
            seat
            for seat in order
            if ActionTiming.INTERRUPT in permitted_timings_in(game, step, seat)
            and interrupt_actions(game, seat)
        ),
        None,
    )
    if first is None:
        return False
    game.round_stack.append(game.round)
    game.round = replace(step, priority=first)
    return True


def _window_timings(game: GameState) -> RoundTimings:
    if not action_is_unstoppable(game):
        return INTERRUPT_TIMINGS
    acting_is_active = game.action_seat is game.active
    return RoundTimings(
        active=frozenset({ActionTiming.INTERRUPT}) if acting_is_active else frozenset(),
        others=frozenset() if acting_is_active else frozenset({ActionTiming.INTERRUPT}),
    )


def play_interrupt(game: GameState, seat: PlayerId, card_id: str, key: str | None = None) -> None:
    """Take the Interrupt keyed ``key`` on ``card_id`` against the held action. Where the forecast
    holds several effects it could answer, ask which first."""
    card, interrupt, _ = _offer(game, seat, card_id, key)
    answered = answered_by(game, card, interrupt, foreseen_now(game))
    if len(answered) == 1 or interrupt.answers_every:
        _play(game, seat, card_id, key, answered[0])
        return
    game.pending = ChooseInterruptEffect(
        seat=seat,
        candidates=tuple(as_modified(game, effect).narrate(game) for effect in answered),
        question="Which effect?",
        resolver=INTERRUPT_EFFECT_QUESTION,
        source_id=card_id,
        resolver_context=(key or "",),
    )


def _offer(
    game: GameState, seat: PlayerId, card_id: str, key: str | None
) -> tuple[L5RCard, Interrupt, CardLocation]:
    """The seat's offer of ``card_id``'s Interrupt keyed ``key``. Raise ``RuntimeError`` if it is
    no longer one the seat can take."""
    offer = next(
        (
            offer
            for offer in card_interrupts_for(game, seat, foreseen_now(game))
            if offer[0].id == card_id and offer[1].key == key
        ),
        None,
    )
    if offer is None:
        raise RuntimeError(f"{card_id} is no longer an Interrupt {seat.name} can take")
    return offer


# The label a ChooseInterruptEffect carries in its resolver slot. It is answered by its own
# handler and names no registered resolver.
INTERRUPT_EFFECT_QUESTION = "interrupt_effect"


def apply_interrupt_effect(
    game: GameState, request: ChooseInterruptEffect, response: DecisionResponse
) -> None:
    """Take the Interrupt against the effect the seat picked. Raise ``RuntimeError`` if the card
    is no longer one the seat can take the Interrupt with."""
    key = request.resolver_context[0] or None
    answered = _answerable(game, request.seat, request.source_id, key)
    effect = _named(
        answered, lambda effect: as_modified(game, effect).narrate(game) == response.choices[0]
    )
    _play(game, request.seat, request.source_id, key, effect)


def _answerable(game: GameState, seat: PlayerId, card_id: str, key: str | None) -> list[Effect]:
    card, interrupt, _ = _offer(game, seat, card_id, key)
    return answered_by(game, card, interrupt, foreseen_now(game))


def _named(effects: list[Effect], matches: Callable[[Effect], bool]) -> Effect:
    """The first of ``effects`` that ``matches``. Raise ``RuntimeError`` if none does: the answer
    names an effect the forecast no longer holds."""
    found = next((effect for effect in effects if matches(effect)), None)
    if found is None:
        raise RuntimeError("the effect answered is no longer among the action's")
    return found


def apply_interrupt_target(
    game: GameState, request: ChooseInterruptTarget, response: DecisionResponse
) -> None:
    """Take the Interrupt against the chosen target. Raise ``RuntimeError`` if the target is no
    longer one the Interrupt can be taken against."""
    key = request.interrupt_key
    answered = _answerable(game, request.seat, request.card_id, key)
    effect = _named(answered, lambda effect: effect.describe() == request.effect)
    _play(game, request.seat, request.card_id, key, effect, response.choices[0])


def _play(
    game: GameState,
    seat: PlayerId,
    card_id: str,
    key: str | None,
    effect: Effect,
    target_id: str | None = None,
) -> None:
    foreseen = foreseen_now(game)
    card, interrupt, location = _offer(game, seat, card_id, key)
    if effect not in answered_by(game, card, interrupt, foreseen):
        raise RuntimeError(f"{card_id} no longer answers {effect.describe()}")
    if interrupt.targets is None:
        interruption = interrupt.interrupt(game, card, effect)
    else:
        candidates = interrupt.targets(game, card, effect)
        if target_id is None:
            game.pending = ChooseInterruptTarget(
                seat=seat,
                candidates=candidates,
                card_id=card.id,
                card_name=card.name,
                effect=effect.describe(),
                interrupt_key=key,
            )
            return
        if target_id not in candidates:
            raise RuntimeError(f"{target_id} is no longer a target {card_id} can be taken against")
        target = game.table.cards_by_id[target_id]
        interruption = interrupt.interrupt(game, card, effect, target)
    if interrupt.answers_every:
        bound = answered_by(game, card, interrupt, foreseen)
        game.modifications.extend(
            Replacement(bound=each, card_id=card.id, target_id=target_id, interrupt_key=key)
            for each in bound
        )
    elif interruption.replacement != effect:
        game.modifications.append(
            Replacement(
                bound=effect,
                card_id=card.id,
                target_id=target_id,
                replacement=_settled(game, interruption.replacement),
                interrupt_key=key,
            )
        )
    if _plays_card(interrupt, location):
        play_strategy_with(game, card, interruption.effects)
        return
    purchase = interrupt.purchase(game, card, plays_card=False)
    paid = priced_cost(game, purchase, interrupt.cost(game, card))
    claimed = _claim(game, seat, card, interrupt)
    triggers.resolve_effects(game, [*claimed, *paid, *interruption.effects])


def _claim(game: GameState, seat: PlayerId, card: L5RCard, interrupt: Interrupt) -> list[Effect]:
    """Spend the use of ``interrupt`` its limit counts. A once-per-action use is recorded now, and a
    once-per-turn use is returned as the effect that claims it, to resolve with the cost."""
    match interrupt.limit:
        case InterruptLimit.ONCE_PER_TURN:
            return [SpendOncePerTurn(card.id, INTERRUPT_TAG)]
        case InterruptLimit.ONCE_PER_ACTION:
            game.interrupts_taken.add((_action_tag(card, interrupt), seat))
            return []
        case InterruptLimit.UNLIMITED:
            return []


def _settled(game: GameState, replacement: Effect) -> Effect | None:
    """A substituted targeting built against its new target now, so what the step forecasts is
    what resolves; None for any other replacement, which the card is asked for as the effect comes
    up."""
    if isinstance(replacement, ResolveAbility) and replacement.effects is None:
        return replacement.built(game)
    return None

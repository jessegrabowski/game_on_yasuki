from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.costs import can_pay
from yasuki_core.engine.rules.abilities.activation import ResolveAbility
from yasuki_core.engine.rules.abilities.model import CardLocation, Interrupt
from yasuki_core.engine.rules.abilities.registry import ability_for, interrupt_for
from yasuki_core.engine.rules.abilities.strategy import play_strategy_with
from yasuki_core.engine.rules.board.queries import has_keyword
from yasuki_core.engine.rules.effects import (
    AttackEffect,
    Discard,
    Effect,
    Fear,
    GainHonor,
    SpendOncePerTurn,
    Then,
)
from yasuki_core.engine.rules.gold.cost import effective_gold_cost
from yasuki_core.engine.rules.gold.producers import reachable_gold
from yasuki_core.engine.rules.legality import (
    has_presence,
    legal_targets,
    location_permits,
    permitted_timings_in,
    seat_cards,
)
from yasuki_core.engine.rules.state import GameState, used_this_turn
from yasuki_core.engine.rules.turn.structure import (
    INTERRUPT_TIMINGS,
    ActionRound,
    RoundKind,
)
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import (
    Action,
    ActionTiming,
    DiscardToInterrupt,
    PlayInterrupt,
)
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseInterruptAdjustment,
    ChooseInterruptEffect,
    ChooseInterruptTarget,
    DecisionResponse,
)
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard


@dataclass(frozen=True, slots=True)
class RulebookInterrupt[T: Effect]:
    """A rulebook Interrupt every player holds: discard a card carrying ``keyword`` to adjust a
    pending effect of type ``answers`` by one of ``adjustments``.

    Attributes
    ----------
    key : str
        Names the ability, for the once-per-action record.
    label : str
        The ability as the datasheet prints it, which a client offers on the card it discards.
    keyword : str
        The keyword a card must carry to be discarded for it.
    answers : type
        The effect type the Interrupt may be taken against.
    question : str
        What the seat is asked once it has named the card, ahead of ``adjustments``.
    adjustments : tuple of (str, int)
        The adjustments the seat may choose between, each as the seat reads it and as the delta it
        gives the effect.
    adjust : callable
        Maps the pending effect and the chosen delta to the effect that replaces it.
    once_per_action : bool
        Whether a seat may take it once per action, as the datasheet makes of Repeatable on an
        Interrupt unless the ability says otherwise.
    """

    key: str
    label: str
    keyword: str
    answers: type[T]
    question: str
    adjustments: tuple[tuple[str, int], ...]
    adjust: Callable[[T, int], T]
    once_per_action: bool

    def delta_for(self, wording: str) -> int:
        """The delta behind ``wording``, one of the adjustments as the seat reads them."""
        return dict(self.adjustments)[wording]


def _adjust_fear(effect: Fear, delta: int) -> Fear:
    return replace(effect, strength=effect.strength + delta)


def _adjust_honor(effect: GainHonor, delta: int) -> GainHonor:
    return replace(effect, adjustment=effect.adjustment + delta)


# The two rulebook Interrupts the ShE datasheet grants, worded as it prints them. Courage may be
# taken any number of times per action, which the datasheet says in as many words, and Honor once,
# which is its default for a Repeatable Interrupt.
RULEBOOK_INTERRUPTS: tuple[RulebookInterrupt, ...] = (
    RulebookInterrupt(
        key="courage",
        label=(
            "Courage Repeatable Interrupt: If the action has any Fear effects, any number of times "
            "per action, discard a Courage card to give one such effect +2 or -2 strength."
        ),
        keyword=keywords.COURAGE,
        answers=Fear,
        question="Give it +2 or -2 strength?",
        adjustments=(("+2 strength", 2), ("-2 strength", -2)),
        adjust=_adjust_fear,
        once_per_action=False,
    ),
    RulebookInterrupt(
        key="honor",
        label=(
            "Honor Repeatable Interrupt: If the action has any Honor gains or losses, discard an "
            "Honor card to increase or reduce one such gain or loss by 1."
        ),
        keyword=keywords.HONOR,
        answers=GainHonor,
        question="Increase or reduce it by 1?",
        adjustments=(("Increase by 1", 1), ("Reduce by 1", -1)),
        adjust=_adjust_honor,
        once_per_action=True,
    ),
)

_RULEBOOK_INTERRUPTS_BY_KEY = {interrupt.key: interrupt for interrupt in RULEBOOK_INTERRUPTS}


def rulebook_interrupt(key: str) -> RulebookInterrupt[Effect]:
    """The rulebook Interrupt named ``key``. Raise ``KeyError`` for a key the datasheet has none
    for."""
    return _RULEBOOK_INTERRUPTS_BY_KEY[key]


def _hand(game: GameState, seat: PlayerId) -> list[L5RCard]:
    return game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards


def forecast(game: GameState, effects: tuple[Effect, ...]) -> tuple[Effect, ...]:
    """What an action handing ``effects`` to step E is about to do, as the Interrupt step offers
    it: the effects in order, a ``Then``'s contents where it stands, an ability's effects behind
    the :class:`~.ResolveAbility` that targets them, and an attack's outcome behind the attack
    when it reaches on the board as it stands. An effect that is nothing to interrupt, an Honor
    change of zero, is left out. What a choice resolver produces later is not foreseeable and is
    not offered."""
    seen: list[Effect] = []
    for effect in effects:
        if isinstance(effect, Then):
            seen.extend(forecast(game, effect.effects))
            continue
        if effect.is_interruptible():
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
class Adjustment:
    """A rulebook Interrupt's answer to one effect of the action: the adjustment it gives it,
    bound to the effect as the forecast showed it and applied as it comes up to resolve. Two
    Courage discards on one Fear are two of these, each adjusting what the one before left.
    Plain data, so a game with one pending compares equal to its replay.

    Attributes
    ----------
    bound : Effect
        The action's effect, as first handed to step E, that the Interrupt answered.
    key : str
        The rulebook Interrupt taken.
    delta : int
        The adjustment chosen.
    """

    bound: Effect
    key: str
    delta: int

    def answers(self, effect: Effect) -> bool:
        return effect == self.bound

    def apply(self, game: GameState, effect: Effect) -> Effect:
        return rulebook_interrupt(self.key).adjust(effect, self.delta)


@dataclass(frozen=True, slots=True)
class Replacement:
    """A card Interrupt's answer to one effect of the action, bound to the effect as the forecast
    showed it. What resolves instead is asked of the card as the effect comes up, against the
    effect as earlier Interrupts leave it, so a negation after a Courage adjustment negates the
    adjusted Fear. The card's own effects resolved when it was taken.

    Attributes
    ----------
    bound : Effect
        The action's effect, as first handed to step E, that the Interrupt answered.
    card_id : str
        The card whose Interrupt was taken.
    target_id : str, optional
        The target the Interrupt was taken against, for one that takes a target. Default None.
    """

    bound: Effect
    card_id: str
    target_id: str | None = None

    def answers(self, effect: Effect) -> bool:
        return effect == self.bound

    def apply(self, game: GameState, effect: Effect) -> Effect:
        card = game.table.cards_by_id[self.card_id]
        interrupt = interrupt_for(card)
        if interrupt is None:
            raise RuntimeError(f"{self.card_id} prints no Interrupt to apply")
        if self.target_id is None:
            return interrupt.interrupt(game, card, effect).replacement
        target = game.table.cards_by_id[self.target_id]
        return interrupt.interrupt(game, card, effect, target).replacement


def _unique(effects: Iterable[Effect]) -> list[Effect]:
    """``effects`` with later duplicates dropped: two alike in every field are one answer, since a
    modification binds to the effect by value and the first to resolve takes it."""
    return list(dict.fromkeys(effects))


def discardable_for(game: GameState, seat: PlayerId, interrupt: RulebookInterrupt) -> list[L5RCard]:
    """The cards ``seat`` holds that ``interrupt`` may discard."""
    return [card for card in _hand(game, seat) if has_keyword(game, card, interrupt.keyword)]


def rulebook_interrupts_for(
    game: GameState, seat: PlayerId, foreseen: tuple[Effect, ...]
) -> list[RulebookInterrupt]:
    """The rulebook Interrupts ``seat`` could take against an action about to do ``foreseen``:
    answering one of them, not already spent on this action where once is the limit, and with a
    card to discard."""
    return [
        interrupt
        for interrupt in RULEBOOK_INTERRUPTS
        if any(isinstance(as_modified(game, effect), interrupt.answers) for effect in foreseen)
        and not (interrupt.once_per_action and (interrupt.key, seat) in game.interrupts_taken)
        and discardable_for(game, seat, interrupt)
    ]


# The once-per-turn tag an Interrupt taken from play is claimed under (CR, Using Abilities 0.3).
INTERRUPT_TAG = "interrupt"


def card_interrupts_for(
    game: GameState, seat: PlayerId, foreseen: tuple[Effect, ...]
) -> list[tuple[L5RCard, Interrupt, CardLocation]]:
    """The Interrupts ``seat`` could take against an action about to do ``foreseen``, each with
    where it is taken from, while the seat has a unit at any battle being fought (CR, Rule of
    Presence).

    A Strategy in hand is offered when its Interrupt answers one of the effects and the seat can
    reach its Gold Cost. A card in play, on the battlefield or face up in a Province, is offered
    under the gates an activated ability answers to: unbowed, within the Rules of Location, unused
    this turn where the arc makes abilities once per turn, and able to pay the Interrupt's cost.
    """
    if not has_presence(game, seat):
        return []
    offered: list[tuple[L5RCard, Interrupt, CardLocation]] = []
    once = ruleset.ACTIVE.abilities_once_per_turn
    for location, card in seat_cards(game, seat):
        interrupt = _answering(game, card, foreseen, location)
        if interrupt is None:
            continue
        if location is CardLocation.HAND:
            if effective_gold_cost(game, card) <= reachable_gold(game, seat, card):
                offered.append((card, interrupt, location))
            continue
        if card.bowed or not location_permits(game, card):
            continue
        if once and used_this_turn(game, card, INTERRUPT_TAG):
            continue
        if can_pay(game, card, interrupt.cost):
            offered.append((card, interrupt, location))
    return offered


def _answering(
    game: GameState, card: L5RCard, foreseen: tuple[Effect, ...], location: CardLocation
) -> Interrupt | None:
    """``card``'s Interrupt if it is taken from ``location`` and answers one of ``foreseen``."""
    interrupt = interrupt_for(card)
    if interrupt is None or location not in interrupt.located_at:
        return None
    if not answered_by(game, card, interrupt, foreseen):
        return None
    return interrupt


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
    """The Interrupts ``seat`` may take against the action held at the Interrupt step, as actions:
    a :class:`~.DiscardToInterrupt` per card a rulebook Interrupt could discard, and a
    :class:`~.PlayInterrupt` per card printing an Interrupt that answers the forecast."""
    foreseen = foreseen_now(game)
    discards: list[Action] = [
        DiscardToInterrupt(card.id, interrupt.key)
        for interrupt in rulebook_interrupts_for(game, seat, foreseen)
        for card in discardable_for(game, seat, interrupt)
    ]
    plays: list[Action] = [
        PlayInterrupt(card.id) for card, _, _ in card_interrupts_for(game, seat, foreseen)
    ]
    return discards + plays


def open_interrupt_window(game: GameState) -> bool:
    """Open the Interrupt step over the action just held, as a round of its own, and report
    whether it opened (CR, Action Sequence step D; ShE datasheet, Interrupt).

    Only when a seat entitled to act holds an Interrupt to take: a step nobody could act in is a
    pass nobody needs to be asked for. Nobody during a Response Step, since a Response is not
    interruptible. The active player acts first.
    """
    if game.round.kind is RoundKind.RESPONSE:
        return False
    step = ActionRound(timings=INTERRUPT_TIMINGS, priority=game.active, kind=RoundKind.INTERRUPT)
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


def play_interrupt(game: GameState, seat: PlayerId, card_id: str) -> None:
    """Take the Interrupt ``card_id`` prints against the held action. Where the forecast holds
    several effects it could answer, ask which first."""
    answered = _answerable(game, seat, card_id, None)
    if len(answered) == 1:
        _play(game, seat, card_id, answered[0])
        return
    _ask_which(game, seat, card_id, None, answered)


def discard_to_interrupt(game: GameState, seat: PlayerId, card_id: str, key: str) -> None:
    """Take the rulebook Interrupt ``key``, discarding ``card_id`` for it, against the held action.
    Where the forecast holds several effects it could answer, ask which first, then the
    adjustment."""
    answered = _answerable(game, seat, card_id, key)
    if len(answered) == 1:
        _ask_adjustment(game, seat, card_id, key, answered[0])
        return
    _ask_which(game, seat, card_id, key, answered)


def _ask_which(
    game: GameState, seat: PlayerId, card_id: str, key: str | None, answered: list[Effect]
) -> None:
    game.pending = ChooseInterruptEffect(
        seat=seat,
        candidates=tuple(effect.narrate(game) for effect in answered),
        question="Which effect?",
        resolver=INTERRUPT_EFFECT_QUESTION,
        source_id=card_id,
        resolver_context=(key or "",),
    )


def _answerable(game: GameState, seat: PlayerId, card_id: str, key: str | None) -> list[Effect]:
    """The forecast effects the seat's ``card_id`` may answer, through the rulebook Interrupt
    ``key`` or the card's own. Raise ``RuntimeError`` if the card is no longer one it can take."""
    foreseen = foreseen_now(game)
    if key is not None:
        taken = next(
            (
                interrupt
                for interrupt in rulebook_interrupts_for(game, seat, foreseen)
                if interrupt.key == key
                and card_id in {card.id for card in discardable_for(game, seat, interrupt)}
            ),
            None,
        )
        if taken is None:
            raise RuntimeError(
                f"{card_id} is no longer a card {seat.name} can discard to interrupt"
            )
        return _unique(
            effect for effect in foreseen if isinstance(as_modified(game, effect), taken.answers)
        )
    played = next(
        (offer for offer in card_interrupts_for(game, seat, foreseen) if offer[0].id == card_id),
        None,
    )
    if played is None:
        raise RuntimeError(f"{card_id} is no longer an Interrupt {seat.name} can play")
    card, interrupt, _ = played
    return answered_by(game, card, interrupt, foreseen)


# The label a ChooseInterruptEffect or ChooseInterruptAdjustment carries in its resolver slot;
# each is answered by its own handler and names no registered resolver.
INTERRUPT_EFFECT_QUESTION = "interrupt_effect"
INTERRUPT_ADJUSTMENT_QUESTION = "interrupt_adjustment"


def apply_interrupt_effect(
    game: GameState, request: ChooseInterruptEffect, response: DecisionResponse
) -> None:
    """Take the Interrupt against the effect the seat picked. Raise ``RuntimeError`` if the card
    is no longer one the seat can take the Interrupt with."""
    key = request.resolver_context[0] or None
    answered = _answerable(game, request.seat, request.source_id, key)
    effect = _named(answered, lambda effect: effect.narrate(game) == response.choices[0])
    if key is None:
        _play(game, request.seat, request.source_id, effect)
    else:
        _ask_adjustment(game, request.seat, request.source_id, key, effect)


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
    answered = _answerable(game, request.seat, request.card_id, None)
    effect = _named(answered, lambda effect: effect.describe() == request.effect)
    _play(game, request.seat, request.card_id, effect, response.choices[0])


def _play(
    game: GameState,
    seat: PlayerId,
    card_id: str,
    effect: Effect,
    target_id: str | None = None,
) -> None:
    foreseen = foreseen_now(game)
    played = next(
        (offer for offer in card_interrupts_for(game, seat, foreseen) if offer[0].id == card_id),
        None,
    )
    if played is None:
        raise RuntimeError(f"{card_id} is no longer an Interrupt {seat.name} can play")
    card, interrupt, location = played
    if effect not in answered_by(game, card, interrupt, foreseen):
        raise RuntimeError(f"{card_id} no longer answers {effect.describe()}")
    if interrupt.targets is None:
        interruption = interrupt.interrupt(game, card, effect)
    else:
        candidates = interrupt.targets(game, card, effect)
        if target_id is None:
            game.pending = ChooseInterruptTarget(
                seat, candidates, card.id, card.name, effect.describe()
            )
            return
        if target_id not in candidates:
            raise RuntimeError(f"{target_id} is no longer a target {card_id} can be taken against")
        target = game.table.cards_by_id[target_id]
        interruption = interrupt.interrupt(game, card, effect, target)
    game.modifications.append(Replacement(effect, card.id, target_id))
    if location is CardLocation.HAND:
        play_strategy_with(game, card, interruption.effects)
        return
    spent = SpendOncePerTurn(card.id, INTERRUPT_TAG)
    triggers.resolve_effects(game, [spent, *interrupt.cost(game, card), *interruption.effects])


def _ask_adjustment(
    game: GameState, seat: PlayerId, card_id: str, key: str, effect: Effect
) -> None:
    taken = rulebook_interrupt(key)
    game.pending = ChooseInterruptAdjustment(
        seat=seat,
        candidates=tuple(wording for wording, _ in taken.adjustments),
        question=f"{effect.narrate(game)}. {taken.question}",
        resolver=INTERRUPT_ADJUSTMENT_QUESTION,
        source_id=card_id,
        resolver_context=(key, effect.describe()),
    )


def apply_interrupt_adjustment(
    game: GameState, request: ChooseInterruptAdjustment, response: DecisionResponse
) -> None:
    """Discard the card and bind the chosen adjustment to the effect it answers. Raise
    ``RuntimeError`` if the card is no longer one the seat can discard to interrupt."""
    key, described = request.resolver_context
    taken = rulebook_interrupt(key)
    answered = _answerable(game, request.seat, request.source_id, key)
    effect = _named(answered, lambda effect: effect.describe() == described)
    if taken.once_per_action:
        game.interrupts_taken.add((taken.key, request.seat))
    game.modifications.append(Adjustment(effect, key, taken.delta_for(response.choices[0])))
    triggers.resolve_effects(game, [Discard(request.source_id, request.seat)])

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.costs import can_pay
from yasuki_core.engine.rules.abilities.activation import ResolveAbility
from yasuki_core.engine.rules.abilities.model import CardLocation, Interrupt
from yasuki_core.engine.rules.abilities.registry import interrupt_for
from yasuki_core.engine.rules.abilities.strategy import play_strategy_with
from yasuki_core.engine.rules.board.queries import has_keyword
from yasuki_core.engine.rules.effects import (
    AttackEffect,
    Discard,
    Effect,
    Fear,
    GainHonor,
    InterruptWindow,
    SpendOncePerTurn,
    Then,
)
from yasuki_core.engine.rules.gold.cost import effective_gold_cost
from yasuki_core.engine.rules.gold.producers import reachable_gold
from yasuki_core.engine.rules.legality import has_presence, location_permits
from yasuki_core.engine.rules.state import GameState, used_this_turn
from yasuki_core.engine.rules.turn.structure import RoundKind
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseInterrupt,
    ChooseInterruptAdjustment,
    ChooseInterruptEffect,
    DecisionResponse,
    interrupt_choice,
    interrupt_token,
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

RULEBOOK_INTERRUPT_RESOLVER = "rulebook_interrupt"


def rulebook_interrupt(key: str) -> RulebookInterrupt[Effect]:
    """The rulebook Interrupt named ``key``. Raise ``KeyError`` for a key the datasheet has none
    for."""
    return _RULEBOOK_INTERRUPTS_BY_KEY[key]


def _hand(game: GameState, seat: PlayerId) -> list[L5RCard]:
    return game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards


def forecast(game: GameState, effects: tuple[Effect, ...]) -> tuple[Effect, ...]:
    """What an action handing ``effects`` to step E is about to do, as the Interrupt window offers
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
    without spending them: what the window forecasts behind a negated attack is nothing."""
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
    """

    bound: Effect
    card_id: str

    def answers(self, effect: Effect) -> bool:
        return effect == self.bound

    def apply(self, game: GameState, effect: Effect) -> Effect:
        card = game.table.cards_by_id[self.card_id]
        interrupt = interrupt_for(card)
        if interrupt is None:
            raise RuntimeError(f"{self.card_id} prints no Interrupt to apply")
        return interrupt.interrupt(game, card, effect).replacement


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
    reach its Gold Cost. A card in play is offered under the gates an activated ability answers
    to: unbowed, within the Rules of Location, unused this turn where the arc makes abilities
    once per turn, and able to pay the Interrupt's cost.
    """
    if not has_presence(game, seat):
        return []
    offered: list[tuple[L5RCard, Interrupt, CardLocation]] = []
    for card in _hand(game, seat):
        interrupt = _answering(game, card, foreseen, CardLocation.HAND)
        if interrupt is not None and effective_gold_cost(game, card) <= reachable_gold(
            game, seat, card
        ):
            offered.append((card, interrupt, CardLocation.HAND))
    once = ruleset.ACTIVE.abilities_once_per_turn
    for card in game.table.battlefield.cards:
        if card.owner is not seat or card.bowed or not location_permits(game, card):
            continue
        if once and used_this_turn(game, card, INTERRUPT_TAG):
            continue
        interrupt = _answering(game, card, foreseen, CardLocation.BATTLEFIELD)
        if interrupt is not None and can_pay(game, card, interrupt.cost):
            offered.append((card, interrupt, CardLocation.BATTLEFIELD))
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
    the Interrupts already taken leave it, and within its ``applies``."""
    return _unique(
        effect
        for effect in foreseen
        if isinstance(as_modified(game, effect), interrupt.answers)
        and interrupt.applies(game, card, effect)
    )


def interrupters(game: GameState, window: InterruptWindow) -> list[PlayerId]:
    """The seats still to be offered an Interrupt at ``window``, the active player first (ShE
    datasheet, Interrupt).

    Nobody during a Response Step, since a Response is not interruptible. A pass holds until
    someone takes an Interrupt, which reopens the window to every seat, and the window closes
    once every seat has passed in turn (CR, Interrupt Actions: an action round).
    """
    if game.round.kind is RoundKind.RESPONSE:
        return []
    foreseen = forecast(game, window.effects)
    if not foreseen:
        return []
    order = [game.active, *(seat for seat in game.table.seats if seat is not game.active)]
    return [
        seat
        for seat in order
        if not window.has_passed(seat)
        and (
            rulebook_interrupts_for(game, seat, foreseen)
            or card_interrupts_for(game, seat, foreseen)
        )
    ]


def interrupt_request(game: GameState, window: InterruptWindow) -> ChooseInterrupt:
    """The Interrupt offered to the first seat :func:`~.interrupters` names at ``window``."""
    seat = interrupters(game, window)[0]
    foreseen = forecast(game, window.effects)
    discards = tuple(
        interrupt_token(card.id, interrupt.key)
        for interrupt in rulebook_interrupts_for(game, seat, foreseen)
        for card in discardable_for(game, seat, interrupt)
    )
    plays = tuple(card.id for card, _, _ in card_interrupts_for(game, seat, foreseen))
    return ChooseInterrupt(
        seat=seat,
        candidates=discards + plays,
        description="; ".join(effect.narrate(game) for effect in foreseen),
    )


@dataclass(frozen=True, slots=True)
class ReopenWindow:
    """Bring the Interrupt window back once the Interrupt just taken has resolved, with every
    seat's pass cleared: the step is an action round, and a pass holds only until someone acts
    (CR, Interrupt Actions and Action Rounds). Stacked above the stash and beneath the Strategy's
    own work, so the window returns through the same door a pass does.

    Attributes
    ----------
    window : InterruptWindow
        The window as it stood.
    """

    window: InterruptWindow

    def resume(self, game: GameState) -> None:
        triggers.resume_paused_cascade(game, [self.window.reopened()])


def apply_interrupt(game: GameState, request: ChooseInterrupt, response: DecisionResponse) -> None:
    """Act on the seat's answer at the Interrupt window and bring the window back for the next.

    A pass records the seat as passed. Naming a card asks, where the forecast holds several
    effects the card could answer, which one, then a rulebook Interrupt asks for its adjustment,
    and only then is the card discarded or played. Raise
    ``RuntimeError`` if the answer names a card the seat can no longer take the Interrupt with.
    """
    window = _window(game)
    seat = request.seat
    if not response.choices:
        triggers.resume_paused_cascade(game, [window.passed_by(seat)])
        return
    card_id, key = interrupt_choice(response.choices[0])
    answered = _answerable(game, seat, window, card_id, key)
    if len(answered) == 1:
        _take(game, seat, window, card_id, key, answered[0])
        return
    game.pending = ChooseInterruptEffect(
        seat=seat,
        candidates=tuple(effect.narrate(game) for effect in answered),
        question="Which effect?",
        resolver=INTERRUPT_EFFECT_QUESTION,
        source_id=card_id,
        resolver_context=(key or "",),
    )


def _answerable(
    game: GameState, seat: PlayerId, window: InterruptWindow, card_id: str, key: str | None
) -> list[Effect]:
    """The forecast effects the seat's ``card_id`` may answer, through the rulebook Interrupt
    ``key`` or the card's own. Raise ``RuntimeError`` if the card is no longer one it can take."""
    foreseen = forecast(game, window.effects)
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


# The label a ChooseInterruptEffect carries in its resolver slot; answered by its own handler, it
# names no registered resolver.
INTERRUPT_EFFECT_QUESTION = "interrupt_effect"


def apply_interrupt_effect(
    game: GameState, request: ChooseInterruptEffect, response: DecisionResponse
) -> None:
    """Take the Interrupt the seat named against the effect it picked. Raise ``RuntimeError`` if
    the card is no longer one the seat can take the Interrupt with."""
    window = _window(game)
    key = request.resolver_context[0] or None
    answered = _answerable(game, request.seat, window, request.source_id, key)
    effect = _named(answered, lambda effect: effect.narrate(game) == response.choices[0])
    _take(game, request.seat, window, request.source_id, key, effect)


def _named(effects: list[Effect], matches: Callable[[Effect], bool]) -> Effect:
    """The first of ``effects`` that ``matches``. Raise ``RuntimeError`` if none does: the answer
    names an effect the forecast no longer holds."""
    found = next((effect for effect in effects if matches(effect)), None)
    if found is None:
        raise RuntimeError("the effect answered is no longer among the action's")
    return found


def _take(
    game: GameState,
    seat: PlayerId,
    window: InterruptWindow,
    card_id: str,
    key: str | None,
    effect: Effect,
) -> None:
    if key is not None:
        _ask_adjustment(game, seat, window, card_id, key, effect)
    else:
        _play_interrupt(game, seat, window, card_id, effect)


def _window(game: GameState) -> InterruptWindow:
    paused = triggers.paused_effect(game)
    if not isinstance(paused, InterruptWindow):
        raise RuntimeError(f"{type(paused).__name__} opens no Interrupt window")
    return paused


def _play_interrupt(
    game: GameState,
    seat: PlayerId,
    window: InterruptWindow,
    card_id: str,
    effect: Effect,
) -> None:
    foreseen = forecast(game, window.effects)
    played = next(
        (offer for offer in card_interrupts_for(game, seat, foreseen) if offer[0].id == card_id),
        None,
    )
    if played is None:
        raise RuntimeError(f"{card_id} is no longer an Interrupt {seat.name} can play")
    card, interrupt, location = played
    if effect not in answered_by(game, card, interrupt, foreseen):
        raise RuntimeError(f"{card_id} no longer answers {effect.describe()}")
    interruption = interrupt.interrupt(game, card, effect)
    game.modifications.append(Replacement(effect, card.id))
    game.stack.append(ReopenWindow(window))
    if location is CardLocation.HAND:
        play_strategy_with(game, card, interruption.effects)
        return
    spent = SpendOncePerTurn(card.id, INTERRUPT_TAG)
    triggers.resolve_effects(game, [spent, *interrupt.cost(game, card), *interruption.effects])


def _ask_adjustment(
    game: GameState,
    seat: PlayerId,
    window: InterruptWindow,
    card_id: str,
    key: str,
    effect: Effect,
) -> None:
    taken = rulebook_interrupt(key)
    game.pending = ChooseInterruptAdjustment(
        seat=seat,
        candidates=tuple(wording for wording, _ in taken.adjustments),
        question=f"{effect.narrate(game)}. {taken.question}",
        resolver=RULEBOOK_INTERRUPT_RESOLVER,
        source_id=card_id,
        resolver_context=(key, effect.describe()),
    )


@triggers.choice_resolver(RULEBOOK_INTERRUPT_RESOLVER)
def _resolve_rulebook_interrupt(
    game: GameState,
    source_id: str,
    chosen: tuple[str, ...],
    seat: PlayerId,
    resolver_context: tuple[str, ...],
) -> list[Effect]:
    """Discard the named card, bind the adjustment to the effect it answers, and bring the window
    back. The window is still paused: naming the card asked further questions without resuming
    it."""
    key, described = resolver_context
    taken = rulebook_interrupt(key)
    window = _window(game)
    answered = _answerable(game, seat, window, source_id, key)
    effect = _named(answered, lambda effect: effect.describe() == described)
    if taken.once_per_action:
        game.interrupts_taken.add((taken.key, seat))
    game.modifications.append(Adjustment(effect, key, taken.delta_for(chosen[0])))
    return [Discard(source_id, seat), window.reopened()]

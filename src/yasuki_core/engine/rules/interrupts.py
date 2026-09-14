from collections.abc import Callable
from dataclasses import dataclass, replace

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.model import Interrupt
from yasuki_core.engine.rules.abilities.registry import interrupt_for
from yasuki_core.engine.rules.abilities.strategy import play_strategy_with
from yasuki_core.engine.rules.board.queries import has_keyword
from yasuki_core.engine.rules.effects import (
    Discard,
    Effect,
    Fear,
    GainHonor,
    InterruptibleEffect,
)
from yasuki_core.engine.rules.gold.cost import effective_gold_cost
from yasuki_core.engine.rules.gold.producers import reachable_gold
from yasuki_core.engine.rules.legality import has_presence
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.structure import RoundKind
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseInterrupt,
    ChooseInterruptAdjustment,
    DecisionResponse,
    interrupt_choice,
    interrupt_token,
)
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard


@dataclass(frozen=True, slots=True)
class RulebookInterrupt[T: InterruptibleEffect]:
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


def rulebook_interrupt(key: str) -> RulebookInterrupt[InterruptibleEffect]:
    """The rulebook Interrupt named ``key``. Raise ``KeyError`` for a key the datasheet has none
    for."""
    return _RULEBOOK_INTERRUPTS_BY_KEY[key]


def _hand(game: GameState, seat: PlayerId) -> list[L5RCard]:
    return game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards


def discardable_for(game: GameState, seat: PlayerId, interrupt: RulebookInterrupt) -> list[L5RCard]:
    """The cards ``seat`` holds that ``interrupt`` may discard."""
    return [card for card in _hand(game, seat) if has_keyword(game, card, interrupt.keyword)]


def rulebook_interrupts_for(
    game: GameState, seat: PlayerId, effect: Effect
) -> list[RulebookInterrupt]:
    """The rulebook Interrupts ``seat`` could take against ``effect`` right now: answering its
    type, not already spent on this action where once is the limit, and with a card to discard."""
    return [
        interrupt
        for interrupt in RULEBOOK_INTERRUPTS
        if isinstance(effect, interrupt.answers)
        and not (interrupt.once_per_action and (interrupt.key, seat) in game.interrupts_taken)
        and discardable_for(game, seat, interrupt)
    ]


def card_interrupts_for(
    game: GameState, seat: PlayerId, effect: Effect
) -> list[tuple[L5RCard, Interrupt]]:
    """The Interrupts ``seat`` could play from hand against ``effect``: each Strategy whose
    Interrupt answers its type and whose Gold Cost the seat can reach, while the seat has a unit
    at any battle being fought (CR, Rule of Presence)."""
    if not has_presence(game, seat):
        return []
    playable: list[tuple[L5RCard, Interrupt]] = []
    for card in _hand(game, seat):
        interrupt = interrupt_for(card)
        if (
            interrupt is not None
            and isinstance(effect, interrupt.answers)
            and effective_gold_cost(game, card) <= reachable_gold(game, seat, card)
        ):
            playable.append((card, interrupt))
    return playable


def interrupters(game: GameState, effect: InterruptibleEffect) -> list[PlayerId]:
    """The seats still to be offered an Interrupt against ``effect``, the active player first
    (ShE datasheet, Interrupt).

    Nobody against an effect that is not interruptible, nobody outside an action, since there is
    nothing to interrupt, and nobody during a Response Step, since a Response is not
    interruptible. A seat that declined is not asked again, and a seat that interrupted is, until
    it declines or has nothing left to take. "Inside an action" means ``game.action`` is set,
    which also reaches an effect a triggered trait raised during the action, a wider window than
    the datasheet's "the action's" effects.
    """
    if not effect.is_interruptible() or game.action is None:
        return []
    if game.round.kind is RoundKind.RESPONSE:
        return []
    order = [game.active, *(seat for seat in game.table.seats if seat is not game.active)]
    return [
        seat
        for seat in order
        if not effect.has_declined(seat)
        and (rulebook_interrupts_for(game, seat, effect) or card_interrupts_for(game, seat, effect))
    ]


def interrupt_request(game: GameState, effect: InterruptibleEffect) -> ChooseInterrupt:
    """The Interrupt offered to the first seat :func:`~.interrupters` names against ``effect``."""
    seat = interrupters(game, effect)[0]
    discards = tuple(
        interrupt_token(card.id, interrupt.key)
        for interrupt in rulebook_interrupts_for(game, seat, effect)
        for card in discardable_for(game, seat, interrupt)
    )
    plays = tuple(card.id for card, _ in card_interrupts_for(game, seat, effect))
    return ChooseInterrupt(seat=seat, candidates=discards + plays, description=effect.describe())


@dataclass(frozen=True, slots=True)
class ResumeInterrupted:
    """Splice ``effects`` into the cascade an Interrupt paused, once the Strategy that answered it
    has resolved. Stacked above the stash and beneath the Strategy's own work, so the answer
    rejoins the cascade through the same door a rulebook discard does.

    Attributes
    ----------
    effects : tuple of Effect
        What stands in for the interrupted effect.
    """

    effects: tuple[Effect, ...]

    def resume(self, game: GameState) -> None:
        triggers.resume_paused_cascade(game, list(self.effects))


def apply_interrupt(game: GameState, request: ChooseInterrupt, response: DecisionResponse) -> None:
    """Act on the seat's answer and bring the paused effect back for the next answer.

    A pass records the seat as declined. A rulebook discard names its card here and asks for the
    adjustment next, leaving the effect paused until that is answered. A Strategy is played the
    way any Strategy is, with the replacement its Interrupt returns queued to rejoin the cascade
    once the Strategy has resolved. Raise ``RuntimeError`` if the answer names a card the seat can
    no longer take the Interrupt with.
    """
    effect = _interrupted(game)
    seat = request.seat
    if not response.choices:
        triggers.resume_paused_cascade(game, [effect.declined_by(seat)])
        return
    card_id, key = interrupt_choice(response.choices[0])
    if key is None:
        _play_interrupt(game, seat, effect, card_id)
    else:
        _ask_adjustment(game, seat, effect, card_id, key)


def _interrupted(game: GameState) -> InterruptibleEffect:
    effect = triggers.paused_effect(game)
    if not isinstance(effect, InterruptibleEffect):
        raise RuntimeError(f"{type(effect).__name__} opens no Interrupt step")
    return effect


def _play_interrupt(
    game: GameState, seat: PlayerId, effect: InterruptibleEffect, card_id: str
) -> None:
    played = next(
        (pair for pair in card_interrupts_for(game, seat, effect) if pair[0].id == card_id), None
    )
    if played is None:
        raise RuntimeError(f"{card_id} is no longer an Interrupt {seat.name} can play")
    card, interrupt = played
    interruption = interrupt.interrupt(game, card, effect)
    game.stack.append(ResumeInterrupted((interruption.replacement,)))
    play_strategy_with(game, card, interruption.effects)


def _ask_adjustment(
    game: GameState, seat: PlayerId, effect: InterruptibleEffect, card_id: str, key: str
) -> None:
    taken = next(
        (
            interrupt
            for interrupt in rulebook_interrupts_for(game, seat, effect)
            if interrupt.key == key
            and card_id in {card.id for card in discardable_for(game, seat, interrupt)}
        ),
        None,
    )
    if taken is None:
        raise RuntimeError(f"{card_id} is no longer a card {seat.name} can discard to interrupt")
    game.pending = ChooseInterruptAdjustment(
        seat=seat,
        candidates=tuple(wording for wording, _ in taken.adjustments),
        question=f"{effect.describe()}. {taken.question}",
        resolver=RULEBOOK_INTERRUPT_RESOLVER,
        source_id=card_id,
        resolver_context=(key,),
    )


@triggers.choice_resolver(RULEBOOK_INTERRUPT_RESOLVER)
def _resolve_rulebook_interrupt(
    game: GameState,
    source_id: str,
    chosen: tuple[str, ...],
    seat: PlayerId,
    resolver_context: tuple[str, ...],
) -> list[Effect]:
    """Discard the named card and splice the adjusted effect in where the interrupted one stood.
    The cascade is still paused on that effect: naming the card asked a second question without
    resuming it."""
    taken = rulebook_interrupt(resolver_context[0])
    if taken.once_per_action:
        game.interrupts_taken.add((taken.key, seat))
    return [Discard(source_id, seat), taken.adjust(_interrupted(game), taken.delta_for(chosen[0]))]

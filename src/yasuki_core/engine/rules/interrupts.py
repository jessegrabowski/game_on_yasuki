from collections.abc import Callable
from dataclasses import dataclass, replace

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.board.queries import has_keyword
from yasuki_core.engine.rules.effects import (
    Discard,
    Effect,
    Fear,
    GainHonor,
    InterruptingEffect,
    adjusted_honor_change,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.structure import RoundKind
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseInterrupt,
    DecisionResponse,
    interrupt_choice,
    interrupt_token,
)
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard


@dataclass(frozen=True, slots=True)
class RulebookInterrupt:
    """A rulebook Interrupt every player holds: discard a card carrying ``keyword`` to adjust a
    pending effect of type ``answers`` by one of ``deltas``.

    Attributes
    ----------
    key : str
        Names the ability, for the once-per-action record.
    keyword : str
        The keyword a card must carry to be discarded for it.
    answers : type
        The effect type the Interrupt may be taken against.
    deltas : tuple of int
        The adjustments the seat may choose between.
    adjust : callable
        Maps the pending effect and the chosen delta to the effect that replaces it.
    once_per_action : bool
        Whether a seat may take it once per action, as the datasheet makes of Repeatable on an
        Interrupt unless the ability says otherwise.
    """

    key: str
    keyword: str
    answers: type[Effect]
    deltas: tuple[int, ...]
    adjust: Callable[..., Effect]
    once_per_action: bool


def _adjust_fear(effect: Fear, delta: int) -> Fear:
    return replace(effect, strength=effect.strength + delta)


def _adjust_honor(effect: GainHonor, delta: int) -> GainHonor:
    return replace(effect, amount=adjusted_honor_change(effect.amount, delta))


# The two rulebook Interrupts the ShE datasheet grants. Courage may be taken any number of times per
# action, which the datasheet says in as many words, and Honor once, which is its default for a
# Repeatable Interrupt.
RULEBOOK_INTERRUPTS: tuple[RulebookInterrupt, ...] = (
    RulebookInterrupt(
        key="courage",
        keyword=keywords.COURAGE,
        answers=Fear,
        deltas=(2, -2),
        adjust=_adjust_fear,
        once_per_action=False,
    ),
    RulebookInterrupt(
        key="honor",
        keyword=keywords.HONOR,
        answers=GainHonor,
        deltas=(1, -1),
        adjust=_adjust_honor,
        once_per_action=True,
    ),
)


def discardable_for(game: GameState, seat: PlayerId, interrupt: RulebookInterrupt) -> list[L5RCard]:
    """The cards ``seat`` holds that ``interrupt`` may discard."""
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    return [card for card in hand.cards if has_keyword(game, card, interrupt.keyword)]


def _taken_key(interrupt: RulebookInterrupt, seat: PlayerId) -> str:
    return f"{interrupt.key}:{seat.name}"


def rulebook_interrupts_for(
    game: GameState, seat: PlayerId, effect: Effect
) -> list[RulebookInterrupt]:
    """The rulebook Interrupts ``seat`` could take against ``effect`` right now: answering its
    type, not already spent on this action where once is the limit, and with a card to discard."""
    return [
        interrupt
        for interrupt in RULEBOOK_INTERRUPTS
        if isinstance(effect, interrupt.answers)
        and not (interrupt.once_per_action and _taken_key(interrupt, seat) in game.interrupts_taken)
        and discardable_for(game, seat, interrupt)
    ]


def interrupters(game: GameState, effect: InterruptingEffect) -> list[PlayerId]:
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
        if not effect.has_declined(seat) and rulebook_interrupts_for(game, seat, effect)
    ]


def interrupt_request(game: GameState, effect: InterruptingEffect) -> ChooseInterrupt:
    """The Interrupt offered to the first seat :func:`~.interrupters` names against ``effect``."""
    seat = interrupters(game, effect)[0]
    discards = tuple(
        interrupt_token(card.id, delta)
        for interrupt in rulebook_interrupts_for(game, seat, effect)
        for card in discardable_for(game, seat, interrupt)
        for delta in interrupt.deltas
    )
    return ChooseInterrupt(seat=seat, candidates=discards, effect=effect)


def apply_interrupt(game: GameState, request: ChooseInterrupt, response: DecisionResponse) -> None:
    """Act on the seat's answer and bring the effect ``request`` guarded back for the next answer.

    A pass marks the seat on the effect, which asks the next seat or resolves. A rulebook discard
    and the adjusted effect are spliced into the paused cascade, and the same seat is asked again
    if it may.

    A discard runs inside the interrupted action's cascade, so a reaction to it fires and it joins
    the action's event record.

    Raise ``RuntimeError`` if the answer names a card the seat can no longer take the Interrupt
    with.
    """
    effect = request.effect
    seat = request.seat
    if not response.choices:
        triggers.resume_paused_cascade(game, [effect.declined_by(seat)])
        return
    card_id, delta = interrupt_choice(response.choices[0])
    _discard_to_interrupt(game, seat, effect, card_id, delta)


def _discard_to_interrupt(
    game: GameState, seat: PlayerId, effect: InterruptingEffect, card_id: str, delta: int
) -> None:
    taken = next(
        (
            interrupt
            for interrupt in rulebook_interrupts_for(game, seat, effect)
            if delta in interrupt.deltas
            and card_id in {card.id for card in discardable_for(game, seat, interrupt)}
        ),
        None,
    )
    if taken is None:
        raise RuntimeError(f"{card_id} is no longer a card {seat.name} can discard to interrupt")
    if taken.once_per_action:
        game.interrupts_taken.add(_taken_key(taken, seat))
    triggers.resume_paused_cascade(game, [Discard(card_id, seat), taken.adjust(effect, delta)])

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
    DecisionResponse,
    interrupt_choice,
    interrupt_token,
)
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard


@dataclass(frozen=True, slots=True)
class RulebookInterrupt[T: InterruptibleEffect]:
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
    answers: type[T]
    deltas: tuple[int, ...]
    adjust: Callable[[T, int], T]
    once_per_action: bool


def _adjust_fear(effect: Fear, delta: int) -> Fear:
    return replace(effect, strength=effect.strength + delta)


def _adjust_honor(effect: GainHonor, delta: int) -> GainHonor:
    return replace(effect, adjustment=effect.adjustment + delta)


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
        interrupt_token(card.id, delta)
        for interrupt in rulebook_interrupts_for(game, seat, effect)
        for card in discardable_for(game, seat, interrupt)
        for delta in interrupt.deltas
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

    A pass records the seat as declined. A rulebook discard splices the discard and the adjusted
    effect into the paused cascade. A Strategy is played the way any Strategy is, with the
    replacement its Interrupt returns queued to rejoin the cascade once the Strategy has resolved.
    Raise ``RuntimeError`` if the answer names a card the seat can no longer take the Interrupt
    with.
    """
    effect = triggers.paused_effect(game)
    if not isinstance(effect, InterruptibleEffect):
        raise RuntimeError(f"{type(effect).__name__} opens no Interrupt step")
    seat = request.seat
    if not response.choices:
        triggers.resume_paused_cascade(game, [effect.declined_by(seat)])
        return
    card_id, delta = interrupt_choice(response.choices[0])
    if delta is None:
        _play_interrupt(game, seat, effect, card_id)
    else:
        _discard_to_interrupt(game, seat, effect, card_id, delta)


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


def _discard_to_interrupt(
    game: GameState, seat: PlayerId, effect: InterruptibleEffect, card_id: str, delta: int
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
        game.interrupts_taken.add((taken.key, seat))
    triggers.resume_paused_cascade(game, [Discard(card_id, seat), taken.adjust(effect, delta)])

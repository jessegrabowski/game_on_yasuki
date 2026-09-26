from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.model import (
    CardLocation,
    Interrupt,
    InterruptLimit,
    Interruption,
)
from yasuki_core.engine.rules.abilities.registry import register_keyword_interrupt
from yasuki_core.engine.rules.effects import (
    AdjustPending,
    AskOption,
    AttackEffect,
    Discard,
    Effect,
    Fear,
    GainHonor,
)
from yasuki_core.engine.rules.interrupts import as_modified, foreseen_now
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import Resolver, choice_resolver
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard

COURAGE_INTERRUPT = "courage"
HONOR_INTERRUPT = "honor"

COURAGE_LABEL = (
    "Courage Repeatable Interrupt: If the action has any Fear effects, any number of times per "
    "action, discard a Courage card to give one such effect +2 or -2 strength."
)
HONOR_LABEL = (
    "Honor Repeatable Interrupt: If the action has any Honor gains or losses, discard an Honor card "
    "to increase or reduce one such gain or loss by 1."
)

_COURAGE_RESOLVER = "courage_interrupt"
_HONOR_RESOLVER = "honor_interrupt"

_COURAGE_ADJUSTMENTS = {"+2 strength": 2, "-2 strength": -2}
_HONOR_ADJUSTMENTS = {"Increase by 1": 1, "Reduce by 1": -1}


# The datasheet discards the card to take the Interrupt, and the adjustment is chosen after. Here
# the seat is asked first and its answer discards the card, which is the wrong order by the CR. The
# order is deliberate. Cancel is offered until the board changes, and the discard changes it. A
# discard can set off something that cannot be taken back, such as a Ring of the Void becoming
# legal and entering play, and the seat could then no longer back out of a question it had not yet
# answered. Asked first, backing out of the question leaves the card in hand. The CR puts nothing
# between the discard and the choice, so no card can tell the two orders apart.
def _asks(
    question: str, adjustments: dict[str, int], resolver: str
) -> Callable[[GameState, L5RCard, Effect], Interruption]:
    def interrupt(game: GameState, card: L5RCard, effect: Effect) -> Interruption:
        ask = AskOption(
            seat=card.owner,
            options=tuple(adjustments),
            question=f"{as_modified(game, effect).narrate(game)}. {question}",
            resolver=resolver,
            source_id=card.id,
            resolver_context=(effect.describe(),),
        )
        return Interruption(replacement=effect, effects=(ask,))

    return interrupt


def _adjusts(adjustments: dict[str, int]) -> Resolver:
    """The choice resolver binding the adjustment the seat picked from ``adjustments``."""

    def resolve(
        game: GameState,
        source_id: str,
        choices: tuple[str, ...],
        seat: PlayerId,
        resolver_context: tuple[str, ...],
    ) -> list[Effect]:
        delta = adjustments[choices[0]]
        return _adjust_and_discard(game, source_id, seat, resolver_context[0], delta)

    return resolve


def _adjust_and_discard(
    game: GameState, card_id: str, seat: PlayerId, described: str, delta: int
) -> list[Effect]:
    """Bind ``delta`` to the held action's effect ``described``, then discard ``card_id``. Raise
    ``RuntimeError`` if the forecast no longer holds the effect."""
    bound = next(
        (
            effect
            for effect in foreseen_now(game)
            if isinstance(effect, AttackEffect | GainHonor) and effect.describe() == described
        ),
        None,
    )
    if bound is None:
        raise RuntimeError("the effect answered is no longer among the action's")
    return [AdjustPending(bound, delta), Discard(card_id, seat)]


choice_resolver(_COURAGE_RESOLVER)(_adjusts(_COURAGE_ADJUSTMENTS))
choice_resolver(_HONOR_RESOLVER)(_adjusts(_HONOR_ADJUSTMENTS))


# The two rulebook Interrupts the ShE datasheet grants, conferred by the keyword on the card they
# discard. Courage may be taken any number of times per action, which its text says in as many
# words, and Honor once, which is the datasheet's reading of Repeatable on an Interrupt.
register_keyword_interrupt(
    Interrupt(
        answers=Fear,
        interrupt=_asks("Give it +2 or -2 strength?", _COURAGE_ADJUSTMENTS, _COURAGE_RESOLVER),
        label=COURAGE_LABEL,
        located_at=(CardLocation.HAND,),
        key=COURAGE_INTERRUPT,
        keywords=frozenset({keywords.COURAGE}),
        limit=InterruptLimit.UNLIMITED,
        from_keyword=keywords.COURAGE,
        from_rulebook=True,
    )
)
register_keyword_interrupt(
    Interrupt(
        answers=GainHonor,
        interrupt=_asks("Increase or reduce it by 1?", _HONOR_ADJUSTMENTS, _HONOR_RESOLVER),
        label=HONOR_LABEL,
        located_at=(CardLocation.HAND,),
        key=HONOR_INTERRUPT,
        keywords=frozenset({keywords.HONOR}),
        limit=InterruptLimit.ONCE_PER_ACTION,
        from_keyword=keywords.HONOR,
        from_rulebook=True,
    )
)

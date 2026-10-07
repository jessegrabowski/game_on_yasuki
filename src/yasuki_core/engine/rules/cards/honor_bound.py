from dataclasses import replace

from yasuki_core.engine.rules.abilities.model import Interrupt, Interruption
from yasuki_core.engine.rules.abilities.registry import register_interrupt
from yasuki_core.engine.rules.effects import Bow, Destroy, Effect, Fear, To
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Okura is Released ---


def _okura_is_released_interrupt(game: GameState, source: L5RCard, effect: Fear) -> Interruption:
    """ "Interrupt: After any Fear effect from the action bows a card, destroy it."

    The destruction depends on the bow actually happening (CR, Independence of Effects), and a
    trait reading "after this bows a card" still fires before it. One play answers every Fear
    effect the action holds.
    """
    destroy = Destroy(effect.target_id, effect.cause)
    outcome = tuple(_okura_is_released_after_bow(step, destroy) for step in effect.outcome)
    return Interruption(replace(effect, outcome=outcome))


def _okura_is_released_after_bow(step: Effect, destroy: Destroy) -> Effect:
    """``step`` of a Fear's outcome with ``destroy`` following its bow, if it is one."""
    match step:
        case Bow():
            return To(step, (destroy,))
        case To(first=Bow()):
            return To(step.first, (*step.contingent, destroy))
        case _:
            return step


register_interrupt(
    "okura_is_released",
    Interrupt(
        answers=Fear,
        interrupt=_okura_is_released_interrupt,
        answers_every=True,
    ),
)

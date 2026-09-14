from dataclasses import replace

from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import (
    Ability,
    CardLocation,
    Interruption,
    itself,
    no_effects,
)
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.effects import Consequence, Effect, Fear
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.game_pieces.cards import L5RCard


# --- Okura is Released ---


def _okura_is_released_interrupt(game: GameState, source: L5RCard, effect: Effect) -> Interruption:
    """ "Interrupt: After any Fear effect from the action bows a card, destroy it."

    The bow still happens, so a trait reading "after this bows a card" still fires, and the
    destruction follows it. Played against one Fear effect: an action producing several needs it
    played against each.
    """
    assert isinstance(effect, Fear)
    return Interruption(
        replace(effect, consequences=effect.consequences + (Consequence.DESTROY,)), []
    )


register_ability(
    "okura_is_released",
    Ability(
        timings=(ActionTiming.INTERRUPT,),
        label="Interrupt: destroy what the action's Fear bows",
        cost=no_cost,
        targets=itself,
        effects=no_effects,
        hits_every_target=True,
        located_at=(CardLocation.HAND,),
        interrupts=(Fear,),
        interrupt=_okura_is_released_interrupt,
    ),
)

from dataclasses import replace

from yasuki_core.engine.rules.abilities.model import Interrupt, Interruption
from yasuki_core.engine.rules.abilities.registry import register_interrupt
from yasuki_core.engine.rules.effects import Destroy, Fear
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Okura is Released ---


def _okura_is_released_interrupt(game: GameState, source: L5RCard, effect: Fear) -> Interruption:
    """ "Interrupt: After any Fear effect from the action bows a card, destroy it."

    The bow still happens, so a trait reading "after this bows a card" still fires, and the
    destruction follows it. Played against one Fear effect: an action producing several needs it
    played against each.
    """
    return Interruption(
        replace(effect, outcome=(*effect.outcome, Destroy(effect.target_id, effect.cause)))
    )


register_interrupt(
    "okura_is_released",
    Interrupt(
        label="Interrupt: destroy what the action's Fear bows",
        answers=Fear,
        interrupt=_okura_is_released_interrupt,
    ),
)

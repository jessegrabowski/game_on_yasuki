from yasuki_core.engine.rules.abilities import (
    Ability,
    bow_cost,
    register_ability,
    register_enters_unbowed,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import Effect, GainHonor
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Poorly Placed Garden ---


register_enters_unbowed("poorly_placed_garden")


def _poorly_placed_garden_targets(game: GameState, source: L5RCard) -> list[str]:
    """The Holding itself. The honor is unconditional, so the ability targets nothing but its own
    source and the board offers no choice."""
    return [source.id]


def _poorly_placed_garden_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [GainHonor(source.owner, 2)]


register_ability(
    "poorly_placed_garden",
    Ability(
        timings=(ActionTiming.LIMITED,),
        label="Limited: bow this Holding to gain 2 Honor",
        cost=bow_cost,
        targets=_poorly_placed_garden_targets,
        effects=_poorly_placed_garden_effects,
        all_targets=True,
    ),
)

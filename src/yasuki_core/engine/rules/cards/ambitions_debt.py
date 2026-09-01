from yasuki_core.engine.rules.abilities import (
    Ability,
    CardLocation,
    no_cost,
    personalities_in_play,
    register_ability,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import Effect, GrantMinimum, GrantModifier
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Uncertainty ---

# "a minimum Chi of 1" and "-2F/-2C", as the card prints them.
MINIMUM_CHI = 1
PENALTY = -2


def _uncertainty_targets(game: GameState, source: L5RCard) -> list[str]:
    """Every Personality in play: the card says "a target Personality" with no side."""
    return [card.id for card in personalities_in_play(game)]


def _uncertainty_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """The minimum, then the penalty, in the order the card prints them.

    A minimum applies on top of the penalties rather than among them (CR, Calculating Stats), so the
    target reads 1 Chi however far the -2C takes him and the Chi Death Rule, which tests for zero,
    never reaches him.
    """
    return [
        GrantMinimum(source.id, target.id, Stat.CHI, MINIMUM_CHI, Duration.UNTIL_END_OF_TURN),
        GrantModifier(source.id, target.id, Stat.FORCE, PENALTY, Duration.UNTIL_END_OF_TURN),
        GrantModifier(source.id, target.id, Stat.CHI, PENALTY, Duration.UNTIL_END_OF_TURN),
    ]


register_ability(
    "uncertainty",
    Ability(
        timings=(ActionTiming.BATTLE, ActionTiming.OPEN),
        label="Battle/Open: A target Personality has a minimum Chi of 1. Give him -2F/-2C",
        cost=no_cost,
        targets=_uncertainty_targets,
        effects=_uncertainty_effects,
        located_at=(CardLocation.HAND,),
    ),
)

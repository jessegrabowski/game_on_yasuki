from yasuki_core.engine.rules.abilities import (
    Ability,
    CardLocation,
    no_cost,
    register_ability,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import Effect, Move
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.units import units_at
from yasuki_core.engine.table import Location
from yasuki_core.game_pieces.cards import L5RCard


# --- Incapacitated ---


def _incapacitated_targets(game: GameState, source: L5RCard) -> list[str]:
    """The Defender's Personalities standing at the battle being fought — the defending army, which
    a Personality kept at home is no part of."""
    attack = game.attack
    if attack is None or attack.current is None:
        return []
    return [card.id for card in units_at(game, attack.current, attack.defender)]


def _incapacitated_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Send the target home. His unit goes with him, which is what moving a Personality means."""
    return [Move(target.id, Location.home(target.owner))]


register_ability(
    "incapacitated",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label="Battle: Move home a target defending Personality",
        cost=no_cost,
        targets=_incapacitated_targets,
        effects=_incapacitated_effects,
        located_at=(CardLocation.HAND,),
    ),
)

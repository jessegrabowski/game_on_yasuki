from yasuki_core.engine.rules.abilities import Ability, bow_cost, register_ability
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import CreateToken, Effect
from yasuki_core.engine.rules.equip import creation_targets
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Weapon Artist ---

FINE_SWORD = "weapon_item_sword_plus2f_plus1c"


def _weapon_artist_targets(game: GameState, source: L5RCard) -> list[str]:
    """The Personalities with room for the sword. It is a One-Handed Weapon, so a Personality
    already carrying a Weapon has nowhere to put it."""
    sword = game.table.creatable_tokens[FINE_SWORD]
    return [target.id for target in creation_targets(game, source.owner, sword)]


def _weapon_artist_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [CreateToken(FINE_SWORD, source.owner, source.id, attach_to=target.id)]


register_ability(
    "weapon_artist",
    Ability(
        timing=ActionTiming.OPEN,
        label="Open: Bow to Equip a +2F/+1C One-Handed Sword to a Personality",
        cost=bow_cost,
        targets=_weapon_artist_targets,
        effects=_weapon_artist_effects,
    ),
)

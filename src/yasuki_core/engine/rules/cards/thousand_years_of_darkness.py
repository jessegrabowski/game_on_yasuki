from yasuki_core.engine.rules.abilities import (
    Ability,
    attack_targets,
    bow_cost,
    register_ability,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import Effect, GainHonor, RangedAttack
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import TriggerContext, on
from yasuki_core.game_pieces.cards import L5RCard


# --- Tosekiki ---

TOSEKIKI_HONOR_LOSS = 3
TOSEKIKI_RANGED = 4


@on(EnteredPlay, "tosekiki")
def _tosekiki_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After this Follower enters play, lose 3 Honor."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [GainHonor(ctx.card.owner, -TOSEKIKI_HONOR_LOSS)]


def _tosekiki_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [RangedAttack(TOSEKIKI_RANGED, target.id, source.owner)]


register_ability(
    "tosekiki",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=f"Battle, Bow: Ranged {TOSEKIKI_RANGED} Attack",
        cost=bow_cost,
        targets=attack_targets,
        effects=_tosekiki_effects,
    ),
)

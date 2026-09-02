from yasuki_core.engine.rules.abilities import Ability, attack_targets, register_ability
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import Effect, GainHonor, PayGold, RangedAttack
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import TriggerContext, on
from yasuki_core.game_pieces.cards import L5RCard


# --- Questionable Vassal ---

VASSAL_HONOR_LOSS = 1
VASSAL_GOLD = 2
VASSAL_RANGED = 3


@on(EnteredPlay, "questionable_vassal")
def _questionable_vassal_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After this Follower enters play, lose 1 Honor."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [GainHonor(ctx.card.owner, -VASSAL_HONOR_LOSS)]


def _questionable_vassal_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [PayGold(source.owner, VASSAL_GOLD, "Questionable Vassal")]


def _questionable_vassal_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [RangedAttack(VASSAL_RANGED, target.id, source.owner)]


register_ability(
    "questionable_vassal",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=f"Battle, {VASSAL_GOLD} Gold: Ranged {VASSAL_RANGED} Attack",
        cost=_questionable_vassal_cost,
        targets=attack_targets,
        effects=_questionable_vassal_effects,
    ),
)

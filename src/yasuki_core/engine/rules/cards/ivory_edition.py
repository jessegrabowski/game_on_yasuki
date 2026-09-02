from yasuki_core.engine.rules.abilities import (
    Ability,
    attack_targets,
    no_cost,
    register_ability,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.attachments import attachment_grant
from yasuki_core.engine.rules.effects import Effect, Fear
from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Daigotsu Roburo ---

ROBURO_FEAR = 4


def _daigotsu_roburo_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Fear(ROBURO_FEAR, target.id, source.owner)]


register_ability(
    "daigotsu_roburo",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=f"Battle: Fear {ROBURO_FEAR}",
        cost=no_cost,
        targets=attack_targets,
        effects=_daigotsu_roburo_effects,
    ),
)


# --- Haramaki-do ---


HARAMAKI_DO_FEAR = 3


@attachment_grant("haramaki_do")
def _haramaki_do_attachment_grant(game: GameState, card: L5RCard, host: L5RCard) -> dict[Stat, int]:
    """This Personality has +1PH. The +2F is printed on the card and needs no handler."""
    return {Stat.PERSONAL_HONOR: 1}


def _haramaki_do_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Fear(HARAMAKI_DO_FEAR, target.id, source.owner)]


register_ability(
    "haramaki_do",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=f"Battle: Fear {HARAMAKI_DO_FEAR}",
        cost=no_cost,
        targets=attack_targets,
        effects=_haramaki_do_effects,
    ),
)

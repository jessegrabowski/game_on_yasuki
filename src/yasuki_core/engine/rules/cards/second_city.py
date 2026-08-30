from yasuki_core.engine.rules.abilities import (
    Ability,
    CardLocation,
    no_cost,
    register_ability,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import DestroyProvince, DrawCard, Effect
from yasuki_core.engine.rules.legality import province_key_holding
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Harsh Choices ---


def _harsh_choices_targets(game: GameState, card: L5RCard) -> list[str]:
    """The Event itself. It names no target — it acts on the Province it is sitting in."""
    return [card.id]


def _harsh_choices_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Destroy the Province the Event sits in, then draw three. Destroying it discards the Province's
    contents face-up, so the Event spends itself in the same stroke and needs no discard of its own.
    """
    province = province_key_holding(game, source.owner, source.id)
    if province is None:
        return []
    return [
        DestroyProvince(source.owner, province),
        *(DrawCard(source.owner) for _ in range(3)),
    ]


register_ability(
    "harsh_choices",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Destroy this Province to draw 3 cards",
        cost=no_cost,
        targets=_harsh_choices_targets,
        effects=_harsh_choices_effects,
        all_targets=True,
        located_at=(CardLocation.PROVINCE,),
    ),
)

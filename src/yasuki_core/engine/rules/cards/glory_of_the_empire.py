from yasuki_core.engine.rules.abilities import (
    Ability,
    bow_cost,
    itself,
    register_ability,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.economy import PlayerState, gold_handler
from yasuki_core.engine.rules.effects import DrawCard, Effect, PayGold
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Traveling Peddler ---

PEDDLER_PRODUCTION = 2
PEDDLER_DRAW_COST = 3


@gold_handler("traveling_peddler")
def _traveling_peddler_gold(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """ "Produce 2 Gold", which the Peddler prints as text rather than as a Gold Production stat."""
    return PEDDLER_PRODUCTION


def _traveling_peddler_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Bow the Peddler and pay 3 Gold. Both, so the bowing this cost spends is not available to
    produce the Peddler's own gold."""
    return [
        *bow_cost(game, source),
        PayGold(source.owner, PEDDLER_DRAW_COST, source.name),
    ]


def _traveling_peddler_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [DrawCard(source.owner)]


register_ability(
    "traveling_peddler",
    Ability(
        timings=(ActionTiming.LIMITED,),
        label=f"Limited, Bow: Pay {PEDDLER_DRAW_COST} gold to draw a card",
        cost=_traveling_peddler_cost,
        targets=itself,
        effects=_traveling_peddler_effects,
        all_targets=True,
    ),
)

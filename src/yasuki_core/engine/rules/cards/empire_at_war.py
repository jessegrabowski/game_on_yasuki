from yasuki_core.engine.rules.abilities import Ability, bow_cost, itself, register_ability
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.economy import PlayerState, gold_handler
from yasuki_core.engine.rules.effects import DrawCard, Effect, PayGold
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard


# --- Ancient Tome ---

# "Open, :g3:, :bow:", as the card prints it.
ANCIENT_TOME_COST = 3


def _ancient_tome_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [PayGold(source.owner, ANCIENT_TOME_COST, source.name), *bow_cost(game, source)]


def _ancient_tome_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [DrawCard(source.owner)]


register_ability(
    "ancient_tome",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open, 3 Gold, Bow: Draw a card",
        cost=_ancient_tome_cost,
        targets=itself,
        effects=_ancient_tome_effects,
        all_targets=True,
    ),
)


# --- Dockside Market ---


@gold_handler("dockside_market")
def _dockside_market_gold(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """+1 GP for controlling any Port, and +1 GP for controlling another Market."""
    bonus = (1 if me.controls(keywords.PORT) else 0) + (
        1 if me.controls(keywords.MARKET, other_than=card) else 0
    )
    return card.gold_production + bonus

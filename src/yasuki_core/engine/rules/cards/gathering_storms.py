from yasuki_core.engine.rules.abilities import (
    Ability,
    banish_top_fate,
    destroy_cost,
    owned_holdings,
    plus_one_gp_this_turn,
    register_ability,
)
from yasuki_core.engine.rules.economy import PlayerState, gold_handler
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    DrawCard,
    Effect,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH


# --- Ancestral Estate ---


@gold_handler("ancestral_estate")
def _ancestral_estate_gold(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """+1 GP while another player's Stronghold has higher Gold Production than yours.

    Your own missing Stronghold counts as producing nothing; an opponent's missing Stronghold has
    no production to compare and never grants the bonus.
    """
    own_production = me.stronghold.gold_production if me.stronghold is not None else 0
    outproduced = any(
        opponent.stronghold is not None and opponent.stronghold.gold_production > own_production
        for opponent in opponents
    )
    return card.gold_production + (1 if outproduced else 0)


# --- Ichiba District ---


def _ichiba_district_targets(game: GameState, card: L5RCard) -> list[str]:
    return [port.id for port in owned_holdings(game, card.owner, keywords.PORT)]


register_ability(
    "ichiba_district",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Banish a Fate card: give a Port +1 Gold Production",
        cost=banish_top_fate,
        targets=_ichiba_district_targets,
        effects=plus_one_gp_this_turn,
    ),
)


# --- Otokoshi District ---


def _otokoshi_district_targets(game: GameState, card: L5RCard) -> list[str]:
    return [market.id for market in owned_holdings(game, card.owner, keywords.MARKET)]


def _otokoshi_district_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [DrawCard(source.owner), AdjustCounter(target.id, WEALTH, 1)]


register_ability(
    "otokoshi_district",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Tireless Open: Destroy this Holding to draw a card and give your target Market a +1GP Wealth token",
        cost=destroy_cost,
        targets=_otokoshi_district_targets,
        effects=_otokoshi_district_effects,
    ),
)

from yasuki_core.engine.rules.abilities import (
    Ability,
    banish_top_fate,
    destroy_cost,
    owned_holdings,
    plus_one_gp_this_turn,
    register_ability,
)
from yasuki_core.engine.rules.economy import PlayerState, gold_handler
from yasuki_core.engine.rules.effects import AdjustCounter, DrawCard, Effect
from yasuki_core.engine.rules.state import GameState, Phase
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH


# --- Ancestral Estate ---


@gold_handler("ancestral_estate")
def _ancestral_estate(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """+1 GP while you are the second player."""
    return card.gold_production + (1 if me.went_second else 0)


# --- Ichiba District ---


def _owned_ports(game: GameState, card: L5RCard) -> list[str]:
    return [port.id for port in owned_holdings(game, card.owner, "Port")]


register_ability(
    "ichiba_district",
    Ability(
        phase=Phase.ACTION,
        label="Banish a Fate card: give a Port +1 Gold Production",
        cost=banish_top_fate,
        targets=_owned_ports,
        effects=plus_one_gp_this_turn,
    ),
)


# --- Otokoshi District ---


def _owned_markets(game: GameState, card: L5RCard) -> list[str]:
    return [market.id for market in owned_holdings(game, card.owner, "Market")]


def _otokoshi_effects(source: L5RCard, target: L5RCard) -> list[Effect]:
    return [DrawCard(source.owner), AdjustCounter(target.id, WEALTH, 1)]


register_ability(
    "otokoshi_district",
    Ability(
        phase=Phase.ACTION,
        label="Destroy: draw a card and give a Market a wealth token",
        cost=destroy_cost,
        targets=_owned_markets,
        effects=_otokoshi_effects,
    ),
)

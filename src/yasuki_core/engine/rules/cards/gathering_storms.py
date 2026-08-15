from yasuki_core.engine.rules.abilities import (
    Ability,
    CardLocation,
    banish_top_fate,
    destroy_cost,
    no_cost,
    owned_holdings,
    plus_one_gp_this_turn,
    register_ability,
)
from yasuki_core.engine.rules.economy import PlayerState, gold_handler
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    DestroyProvince,
    DrawCard,
    Effect,
)
from yasuki_core.engine.rules.legality import province_key_holding
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH


# --- Ancestral Estate ---


@gold_handler("ancestral_estate")
def _ancestral_estate(
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
        timing=ActionTiming.OPEN,
        label="Destroy this Province to draw 3 cards",
        cost=no_cost,
        targets=_harsh_choices_targets,
        effects=_harsh_choices_effects,
        all_targets=True,
        located_at=(CardLocation.PROVINCE,),
    ),
)


# --- Ichiba District ---


def _owned_ports(game: GameState, card: L5RCard) -> list[str]:
    return [port.id for port in owned_holdings(game, card.owner, "Port")]


register_ability(
    "ichiba_district",
    Ability(
        timing=ActionTiming.OPEN,
        label="Banish a Fate card: give a Port +1 Gold Production",
        cost=banish_top_fate,
        targets=_owned_ports,
        effects=plus_one_gp_this_turn,
    ),
)


# --- Otokoshi District ---


def _owned_markets(game: GameState, card: L5RCard) -> list[str]:
    return [market.id for market in owned_holdings(game, card.owner, "Market")]


def _otokoshi_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [DrawCard(source.owner), AdjustCounter(target.id, WEALTH, 1)]


register_ability(
    "otokoshi_district",
    Ability(
        timing=ActionTiming.OPEN,
        label="Destroy: draw a card and give a Market a wealth token",
        cost=destroy_cost,
        targets=_owned_markets,
        effects=_otokoshi_effects,
    ),
)

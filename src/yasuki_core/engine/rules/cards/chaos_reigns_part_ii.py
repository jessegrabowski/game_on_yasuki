from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.economy import effective_keywords
from yasuki_core.engine.rules.abilities import Ability, bow_cost, owned_holdings, register_ability
from yasuki_core.engine.rules.effects import AdjustCounter, Choose, DrawCard, Effect, GrantModifier
from yasuki_core.engine.rules.events import CounterGained, EnteredPlay, TurnStarted
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import (
    TriggerContext,
    at_cap,
    choice_resolver,
    on,
    once_per_turn,
)
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.game_pieces.prints import HoldingPrint


# --- Millet Farm ---


def _owned_farms(game: GameState, card: L5RCard) -> list[str]:
    return [farm.id for farm in owned_holdings(game, card.owner, "Farm")]


def _millet_farm_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [
        GrantModifier(source.id, target.id, Stat.GOLD_PRODUCTION, 2, Duration.UNTIL_END_OF_TURN)
    ]


register_ability(
    "millet_farm",
    Ability(
        timing=ActionTiming.OPEN,
        label="Bow: give a Farm +2 Gold Production",
        cost=bow_cost,
        targets=_owned_farms,
        effects=_millet_farm_effects,
    ),
)


# --- Rice Farm ---


@on(TurnStarted, "rice_farm")
def _rice_farm(ctx: TriggerContext) -> list[Effect]:
    """After your turn begins, give this Holding a +1GP Wealth token (max four)."""
    if ctx.card.owner is not ctx.event.seat or at_cap(ctx.card, WEALTH, 4):
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


# --- Shosuro Aoki / Yoritomo Kayoko (Experienced) ---


@on(CounterGained, "shosuro_aoki_yoritomo_kayoko_experienced")
def _shosuro_aoki(ctx: TriggerContext) -> list[Effect]:
    """After your Holding gains any Wealth tokens, once per turn, draw a card."""
    if ctx.event.counter is not WEALTH:
        return []
    gainer = ctx.game.table.cards_by_id[ctx.event.card_id]
    if not isinstance(gainer.printed, HoldingPrint) or gainer.owner is not ctx.card.owner:
        return []
    if not once_per_turn(ctx.game, ctx.card, "aoki_draw"):
        return []
    return [DrawCard(ctx.card.owner)]


# --- Wheat Farm ---


@on(EnteredPlay, "wheat_farm")
def _wheat_farm(ctx: TriggerContext) -> list[Effect]:
    """After this Holding enters play, let its controller give zero to two other Farms they control a
    +1GP Wealth token."""
    if ctx.event.card_id != ctx.card.id:
        return []
    others = tuple(
        card.id
        for card in ctx.game.table.battlefield.cards
        if card.owner is ctx.card.owner
        and card is not ctx.card
        and isinstance(card.printed, HoldingPrint)
        and "Farm" in effective_keywords(ctx.game, card)
    )
    if not others:
        return []
    return [Choose(ctx.card.owner, others, 0, min(2, len(others)), "wheat_farm", ctx.card.id)]


@choice_resolver("wheat_farm", prompt="Give a Wealth token to other Farms you control")
def _wheat_farm_grant(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [AdjustCounter(card_id, WEALTH, 1) for card_id in chosen]

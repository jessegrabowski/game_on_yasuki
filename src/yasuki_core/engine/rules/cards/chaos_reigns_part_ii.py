from yasuki_core.engine.rules.effects import AdjustCounter, Choose, DrawCard, Effect
from yasuki_core.engine.rules.events import CounterGained, EnteredPlay, TurnStarted
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import (
    TriggerContext,
    at_cap,
    choice_resolver,
    on,
    once_per_turn,
)
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.game_pieces.dynasty import DynastyHolding


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
    gainer = ctx.game.table.cards_by_id.get(ctx.event.card_id)
    if not isinstance(gainer, DynastyHolding) or gainer.owner is not ctx.card.owner:
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
        and isinstance(card, DynastyHolding)
        and "Farm" in card.keywords
    )
    if not others:
        return []
    return [Choose(ctx.card.owner, others, 0, min(2, len(others)), "wheat_farm", ctx.card.id)]


@choice_resolver("wheat_farm")
def _wheat_farm_grant(game: GameState, source_id: str, chosen: tuple[str, ...]) -> list[Effect]:
    return [AdjustCounter(card_id, WEALTH, 1) for card_id in chosen]

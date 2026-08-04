from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Destroy,
    Effect,
    IgnoreHonorRequirements,
    Straighten,
)
from yasuki_core.engine.rules.events import Destroyed, EnteredPlay
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.game_pieces.counters import SINCERITY, WEALTH


# --- Mishime Sensei ---


@on(EnteredPlay, "mishime_sensei")
def _mishime_sensei_enters_play(ctx: TriggerContext) -> list[Effect]:
    """Mishime Sensei: grant its controller the ignore-Honor-Requirements waiver as it enters
    play."""
    if ctx.event.card_id != ctx.card.id or ctx.card.owner is None:
        return []
    return [IgnoreHonorRequirements(ctx.card.owner)]


# --- Modest Farm ---


@choice_resolver("modest_farm_straighten")
def _modest_farm_straighten(
    game: GameState, source_id: str, chosen: tuple[str, ...]
) -> list[Effect]:
    # source_id is the recruited target; chosen holds Modest Farm's id when its controller sacrifices
    # it to straighten the target.
    if not chosen:
        return []
    return [Destroy(chosen[0]), Straighten(source_id)]


# --- Rural Market ---


@on(EnteredPlay, "rural_market")
def _rural_market_enters_play(ctx: TriggerContext) -> list[Effect]:
    """After this Holding enters play, give it a +1GP Wealth token."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


@on(Destroyed, "rural_market")
def _rural_market_farm_destroyed(ctx: TriggerContext) -> list[Effect]:
    """After your Farm is destroyed, give this Holding a +1GP Wealth token."""
    destroyed = ctx.game.table.cards_by_id.get(ctx.event.card_id)
    if destroyed is None or destroyed.owner is not ctx.card.owner:
        return []
    if "Farm" not in destroyed.keywords:
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


# --- Sapphire Mine ---


@on(EnteredPlay, "sapphire_mine")
def _sapphire_mine(ctx: TriggerContext) -> list[Effect]:
    """Sincerity: after this Holding enters play, if it accrued two or more Sincerity tokens, give it
    a +1GP Wealth token."""
    if ctx.event.card_id != ctx.card.id:
        return []
    if ctx.card.counters.get(SINCERITY.key, 0) < 2:
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]

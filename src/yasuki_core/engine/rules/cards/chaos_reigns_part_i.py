from yasuki_core.engine.rules.effects import AdjustCounter, Effect
from yasuki_core.engine.rules.events import CardDiscarded
from yasuki_core.engine.rules.triggers import TriggerContext, at_cap, caused_by, on
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WEALTH


# --- Caravansary ---


@on(CardDiscarded, "caravansary")
def _caravansary(ctx: TriggerContext) -> list[Effect]:
    """If your action discarded a Fate card, give this Holding a +1GP Wealth token (max three)."""
    if not caused_by(ctx, ctx.card.owner) or ctx.event.side is not Side.FATE:
        return []
    if at_cap(ctx.card, WEALTH, 3):
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]

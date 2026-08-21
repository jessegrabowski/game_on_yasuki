from yasuki_core.engine.rules.effects import AdjustCounter, Effect, GainGold
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.triggers import TriggerContext, on
from yasuki_core.game_pieces.counters import SINCERITY, WEALTH


# --- Pawnbroker ---


@on(EnteredPlay, "pawnbroker")
def _pawnbroker_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After this Holding enters play, turn each Sincerity token it accrued into a +1GP Wealth
    token."""
    if ctx.event.card_id != ctx.card.id:
        return []
    sincerity = ctx.card.counters.get(SINCERITY.key, 0)
    if sincerity == 0:
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, sincerity)]


# --- The Kurai District Court ---


@on(EnteredPlay, "the_kurai_district_court")
def _the_kurai_district_court_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After this Holding enters play, produce one Gold for each Sincerity token it accrued."""
    if ctx.event.card_id != ctx.card.id:
        return []
    sincerity = ctx.card.counters.get(SINCERITY.key, 0)
    if sincerity == 0:
        return []
    return [GainGold(ctx.card.owner, sincerity)]

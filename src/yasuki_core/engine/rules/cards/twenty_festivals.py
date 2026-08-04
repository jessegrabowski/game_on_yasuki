from yasuki_core.engine.rules.abilities import InvestAbility, register_invest
from yasuki_core.engine.rules.effects import AdjustCounter, Effect
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH


# --- Questionable Market ---


def _two_wealth(source: L5RCard, amount: int) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, 2)]


register_invest("questionable_market", InvestAbility(minimum=2, maximum=2, effect=_two_wealth))

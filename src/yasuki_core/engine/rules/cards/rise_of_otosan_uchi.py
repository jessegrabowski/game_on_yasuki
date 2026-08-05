from yasuki_core.engine.rules.abilities import InvestAbility, one_wealth, register_invest
from yasuki_core.engine.rules.effects import AdjustCounter, Effect
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH


# --- Courts of Otosan Uchi ---

register_invest("courts_of_otosan_uchi", InvestAbility(minimum=2, maximum=2, effect=one_wealth))


# --- Rebuilt Harbor ---


def _invest_wealth(source: L5RCard, amount: int) -> list[Effect]:
    """One +1GP Wealth token per gold invested — Rebuilt Harbor's variable payoff."""
    return [AdjustCounter(source.id, WEALTH, amount)]


register_invest("rebuilt_harbor", InvestAbility(minimum=1, maximum=3, effect=_invest_wealth))

from yasuki_core.engine.rules.abilities import InvestAbility, register_invest
from yasuki_core.engine.rules.effects import AdjustCounter, Effect
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH


# --- Questionable Market ---


def _questionable_market_invest(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, 2)]


register_invest(
    "questionable_market", InvestAbility(amounts=(2,), effect=_questionable_market_invest)
)

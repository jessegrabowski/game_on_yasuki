from yasuki_core.engine.rules.economy import PlayerState, recruit_discount
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard


# --- Moto Traders ---


@recruit_discount("moto_traders")
def _moto_traders(card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]) -> int:
    """Enters play for 1 less Gold if you control another Merchant Caravan."""
    return 1 if me.controls(keywords.MERCHANT_CARAVAN, other_than=card) else 0

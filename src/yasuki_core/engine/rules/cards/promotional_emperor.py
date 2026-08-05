from yasuki_core.engine.rules.economy import PlayerState, is_clan, recruit_discount
from yasuki_core.game_pieces.cards import L5RCard


# --- Colonial Farm ---


@recruit_discount("colonial_farm")
def _colonial_farm(card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]) -> int:
    """Enters play for 1 less Gold if you are a Lion Clan player."""
    return 1 if is_clan(me, "Lion") else 0

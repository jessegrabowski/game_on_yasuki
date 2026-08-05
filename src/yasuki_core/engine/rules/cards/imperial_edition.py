from yasuki_core.engine.rules.economy import PlayerState, is_clan, recruit_discount
from yasuki_core.game_pieces.cards import L5RCard


# --- Fantastic Gardens ---


@recruit_discount("fantastic_gardens")
def _fantastic_gardens(card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]) -> int:
    """Enters play for 2 less Gold if you are a Crane Clan player."""
    return 2 if is_clan(me, "Crane") else 0

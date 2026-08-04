from yasuki_core.engine.rules.economy import PlayerState, gold_handler
from yasuki_core.game_pieces.cards import L5RCard


# --- Ancestral Estate ---


@gold_handler("ancestral_estate")
def _ancestral_estate(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """+1 GP while you are the second player."""
    return card.gold_production + (1 if me.went_second else 0)

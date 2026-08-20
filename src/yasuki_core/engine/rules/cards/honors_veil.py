from yasuki_core import ruleset
from yasuki_core.engine.rules.economy import PlayerState, gold_handler, is_clan
from yasuki_core.game_pieces.cards import L5RCard


# --- Teardrop Island ---


@gold_handler("teardrop_island")
def _teardrop_island(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """Produce 2 Gold, or 3 while you are a Mantis Clan player."""
    return 3 if is_clan(me, ruleset.MANTIS) else 2

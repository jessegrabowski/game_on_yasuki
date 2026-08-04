from yasuki_core.engine.rules.economy import PlayerState, gold_handler
from yasuki_core.game_pieces.cards import L5RCard


# --- Jade Works ---


@gold_handler("jade_works")
def _jade_works(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """+2 GP when paying for a Jade card."""
    bonus = 2 if any("Jade" in target.keywords for target in targets) else 0
    return card.gold_production + bonus

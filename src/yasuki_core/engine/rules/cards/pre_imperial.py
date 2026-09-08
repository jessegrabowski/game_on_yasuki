from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.gold.production import gold_handler
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard


# --- Jade Works ---


@gold_handler("jade_works")
def _jade_works_gold(
    card: L5RCard, game: GameState, seat: PlayerId, targets: tuple[L5RCard, ...]
) -> int:
    """+2 GP when paying for a Jade card."""
    bonus = 2 if any(keywords.JADE in target.keywords for target in targets) else 0
    return card.gold_production + bonus

from yasuki_core.engine.rules.rulebook.equip import equips_from_discard
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- The Desiccated ---


@equips_from_discard("the_desiccated")
def _the_desiccated_equips_from_discard(game: GameState, card: L5RCard) -> bool:
    """You may Equip this Follower from your discard pile."""
    return True

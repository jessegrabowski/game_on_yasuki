from yasuki_core.engine.rules.economy import PlayerState, gold_handler
from yasuki_core.game_pieces.cards import L5RCard


# --- Dockside Market ---


@gold_handler("dockside_market")
def _dockside_market(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """+1 GP for controlling any Port, and +1 GP for controlling another Market."""
    bonus = (1 if me.controls("Port") else 0) + (1 if me.controls("Market", other_than=card) else 0)
    return card.gold_production + bonus

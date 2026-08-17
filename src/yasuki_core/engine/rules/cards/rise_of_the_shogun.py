from yasuki_core.engine.rules.attachments import attachment_grant
from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Shadowlands Ambassador ---


@attachment_grant("shadowlands_ambassador")
def _shadowlands_ambassador(game: GameState, card: L5RCard, host: L5RCard) -> dict[Stat, int]:
    """This Personality has -1PH. The Force 2 and the -1 Chi are printed on the card. His Reaction,
    which drops the bow cost of an action, is not modeled: a cost is built from the card alone and
    cannot ask what is attached to it."""
    return {Stat.PERSONAL_HONOR: -1}

from yasuki_core.engine.rules.attachments import attachment_grant
from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Haramaki-do ---


@attachment_grant("haramaki_do")
def _haramaki_do_attachment_grant(game: GameState, card: L5RCard, host: L5RCard) -> dict[Stat, int]:
    """This Personality has +1PH. The +2F is printed on the card and needs no handler."""
    return {Stat.PERSONAL_HONOR: 1}

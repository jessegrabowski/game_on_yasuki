from yasuki_core.engine.rules.abilities import bow_waiver
from yasuki_core.engine.rules.attachments import attachment_grant
from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Shadowlands Ambassador ---


@attachment_grant("shadowlands_ambassador")
def _shadowlands_ambassador_attachment_grant(
    game: GameState, card: L5RCard, host: L5RCard
) -> dict[Stat, int]:
    """This Personality has -1PH. The Force 2 and the -1 Chi are printed on the card."""
    return {Stat.PERSONAL_HONOR: -1}


# Once a turn, his Personality may ignore the cost of bowing to pay for one of their own abilities.
bow_waiver("shadowlands_ambassador")

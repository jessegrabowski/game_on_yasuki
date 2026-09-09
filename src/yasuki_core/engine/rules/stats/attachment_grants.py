from collections.abc import Callable

from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.engine.rules.registrar import HandlerRegistry
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# What an attachment grants the card it hangs on, beyond the modifier it prints. Haramaki-do prints
# +2F and says "This Personality has +1PH" in its text; the printed half is a stat on the print, the
# written half is this. Keyed by printed id like the other per-card registries.
GrantHandler = Callable[[GameState, L5RCard, L5RCard], dict[Stat, int]]
ATTACHMENT_GRANTS: HandlerRegistry[GrantHandler] = HandlerRegistry(
    "attachment grants", "already has an attachment grant"
)
attachment_grant = ATTACHMENT_GRANTS.make_decorator()


def granted_stat(game: GameState, attached: L5RCard, host: L5RCard, stat: Stat) -> int:
    """What ``attached``'s own text gives ``host`` for ``stat``, or 0 when it gives nothing."""
    handler = ATTACHMENT_GRANTS.get(attached.printed_id)
    if handler is None:
        return 0
    return handler(game, attached, host).get(stat, 0)

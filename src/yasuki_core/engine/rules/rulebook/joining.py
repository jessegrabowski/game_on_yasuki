from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.registrar import HandlerRegistry
from yasuki_core.engine.rules.rulebook.copies import copy_may_enter
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard

# Cards printing "Will not join a <who> player", by printed id, each with whether it would join a
# seat. To join is to come under a player's control (CR, Join), which a card does as it enters play.
JoinRestriction = Callable[[GameState, PlayerId], bool]
JOIN_RESTRICTIONS: HandlerRegistry[JoinRestriction] = HandlerRegistry(
    "join restrictions", "already restricts which players it joins"
)
register_join_restriction = JOIN_RESTRICTIONS.make_register()


def may_join(game: GameState, seat: PlayerId, card: L5RCard) -> bool:
    """Whether ``card`` may come under ``seat``'s control by entering play: the limits on copies
    allow it, and so does its own "Will not join" text (CR, Join)."""
    restriction = JOIN_RESTRICTIONS.get(card.printed_id)
    return copy_may_enter(game, seat, card) and (restriction is None or restriction(game, seat))

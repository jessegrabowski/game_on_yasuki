from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.registrar import HandlerRegistry
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard

# Cards printing "May only be Recruited by a <who> player", by printed id, each with whether a seat
# is such a player. It binds every Recruit, the rulebook's and an effect's alike.
RecruitRestriction = Callable[[GameState, PlayerId], bool]
RECRUIT_RESTRICTIONS: HandlerRegistry[RecruitRestriction] = HandlerRegistry(
    "recruit restrictions", "already restricts who may Recruit it"
)
register_recruit_restriction = RECRUIT_RESTRICTIONS.make_register()


def may_recruit(game: GameState, seat: PlayerId, card: L5RCard) -> bool:
    """Whether ``card``'s own text lets ``seat`` Recruit it."""
    restriction = RECRUIT_RESTRICTIONS.get(card.printed_id)
    return restriction is None or restriction(game, seat)

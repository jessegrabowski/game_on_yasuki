from yasuki_core import ruleset
from yasuki_core.engine import ops
from yasuki_core.engine.rules.board.queries import rulebook_proxy
from yasuki_core.engine.rules.rulebook import cycle
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import CYCLE_PROXY_ID
from yasuki_core.game_pieces.prints import CardPrint

# The print each rulebook proxy presents, by id. The engine owns these prints, because a rulebook
# ability exists on every table whatever the card catalog holds. A proxy is not a card, so the
# catalog has no record of one and the database never sees it. The registration audit counts these
# ids as known card ids, which lets abilities registered on them pass its check.
RULEBOOK_PROXY_PRINTS: dict[str, CardPrint] = {CYCLE_PROXY_ID: cycle.CYCLE_PROXY}


def spawn_rulebook_proxies(game: GameState) -> None:
    """Deal every seat the proxies the active ruleset names, into its rulebook zone, skipping any
    it already holds. Each proxy's id is fixed by seat and print, so no token count moves."""
    for printed_id in ruleset.ACTIVE.rulebook_proxies:
        printed = RULEBOOK_PROXY_PRINTS[printed_id]
        for seat in game.table.seats:
            if rulebook_proxy(game, seat, printed_id) is None:
                ops.spawn_token(
                    game.table,
                    f"{seat.name}-{printed_id}",
                    printed,
                    seat,
                    dest=ZoneKey(seat, ZoneRole.RULEBOOK),
                )

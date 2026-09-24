from yasuki_core import ruleset
from yasuki_core.engine import ops
from yasuki_core.engine.rules.board.queries import rulebook_proxy
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.prints import CardPrint

# The print each rulebook proxy presents, by id. The rules own these prints: a rulebook ability
# exists on every table whatever the card catalog holds, so they are not read from
# ``creatable_tokens``. The catalog record of the same id carries the printed text the registration
# audit checks and the art the clients draw. Empty until an arc grants a player ability through a
# proxy.
RULEBOOK_PROXY_PRINTS: dict[str, CardPrint] = {}


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

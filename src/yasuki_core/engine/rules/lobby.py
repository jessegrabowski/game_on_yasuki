from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.modifiers import LobbyModifier
from yasuki_core.engine.rules.ongoing_grants import grant_applies
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# What a card in play gives its controller's Lobby amounts, beyond anything it prints. Shigekawa's
# Court reads "You have a +5 Lobby Bonus"; there is no stat for it, so the grant is text. Keyed by
# printed id like the other registries.
LobbyGrant = Callable[[GameState, L5RCard], int]
LOBBY_BONUSES: dict[str, LobbyGrant] = {}


def lobby_bonus_grant(printed_id: str) -> Callable[[LobbyGrant], LobbyGrant]:
    """Register the decorated function as ``printed_id``'s Lobby Bonus grant."""

    def register(grant: LobbyGrant) -> LobbyGrant:
        if printed_id in LOBBY_BONUSES:
            raise ValueError(f"{printed_id} already grants a Lobby Bonus")
        LOBBY_BONUSES[printed_id] = grant
        return grant

    return register


def lobby_bonus(game: GameState, seat: PlayerId) -> int:
    """``seat``'s Lobby Bonus right now: its Penalties are the negative part of the same sum.

    Read wherever a Lobby action checks an amount about a player, whether that player is the one
    acting or one being compared against, because the datasheet applies the adjustment to the player
    the amount is about rather than to the player taking the action (ShE datasheet, Lobby Bonuses
    and Penalties).
    """
    total = 0
    for card in game.table.battlefield.cards:
        if card.owner is not seat:
            continue
        grant = LOBBY_BONUSES.get(card.printed_id)
        if grant is not None:
            total += grant(game, card)
    total += sum(
        recorded.amount
        for recorded in game.modifiers
        if isinstance(recorded, LobbyModifier)
        and recorded.seat is seat
        and grant_applies(game, recorded)
    )
    return total


def lobby_amount(game: GameState, seat: PlayerId, amount: int) -> int:
    """``amount``, about ``seat``, as a Lobby action reads it — its Lobby Bonus included.

    Any amount is adjusted, not only Family Honor: the rulebook Lobby checks Family Honor, but each
    Wind's own Lobby checks something else — cards in hand, the total Gold Cost of attachments
    controlled, the total Force of unbowed Followers and Personalities — and the Bonus applies to
    whichever it is (ShE datasheet, Lobby Bonuses and Penalties).

    Where the amount is Family Honor the adjustment is neither an Honor gain nor an Honor loss, so
    it is applied to the amount being compared and never written back to the seat.
    """
    return amount + lobby_bonus(game, seat)

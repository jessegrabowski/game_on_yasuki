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


# The per-turn mark a Lobby leaves on the Personality it bowed, for the cards that ask who Lobbied.
LOBBIED_TAG = "lobbied"


# What a card in play says about who may not Lobby, keyed by the card's printed id. A bar is a card
# behavior rather than a branch inside the rule, the way a Favor payer is: the card decides which
# seats it stops, since one stops its controller's rivals and another stops its own controller.
LobbyBar = Callable[[GameState, L5RCard, PlayerId], bool]
LOBBY_BARS: dict[str, LobbyBar] = {}


def lobby_bar(printed_id: str) -> Callable[[LobbyBar], LobbyBar]:
    """Register the decorated predicate as ``printed_id``'s bar on Lobbying."""

    def register(bar: LobbyBar) -> LobbyBar:
        if printed_id in LOBBY_BARS:
            raise ValueError(f"{printed_id} already bars Lobbying")
        LOBBY_BARS[printed_id] = bar
        return bar

    return register


def may_lobby(game: GameState, seat: PlayerId) -> bool:
    """Whether nothing in play stops ``seat`` taking a Lobby action.

    Only what a card forbids. The datasheet's own conditions on Lobbying are checked where the
    action's legality is decided.
    """
    return not any(
        bar(game, card, seat)
        for card in game.table.battlefield.cards
        if (bar := LOBBY_BARS.get(card.printed_id)) is not None
    )


# Personalities their controller may not bow to Lobby (the printed "may not Lobby"), by printed id.
# A flag rather than a handler: the card states the restriction flatly and admits no condition. This
# is the card-level half of the rule; :data:`LOBBY_BARS` is the half that stops a whole player.
MAY_NOT_LOBBY: set[str] = set()


def may_not_lobby(printed_id: str) -> None:
    """Register ``printed_id`` as a Personality who cannot be bowed to Lobby."""
    if printed_id in MAY_NOT_LOBBY:
        raise ValueError(f"{printed_id} already may not be bowed to Lobby")
    MAY_NOT_LOBBY.add(printed_id)

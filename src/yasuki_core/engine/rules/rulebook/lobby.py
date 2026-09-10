from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.board import queries
from yasuki_core.engine.rules.vocabulary.decisions import ChooseLobbyTarget, DecisionResponse
from yasuki_core.engine.rules.effects import Bow, TakeFavor
from yasuki_core.engine.rules.vocabulary.modifiers import LobbyModifier
from yasuki_core.engine.rules.stats.ongoing_grants import grant_applies
from yasuki_core.engine.registrar import FlagRegistry, HandlerRegistry
from yasuki_core.engine.rules.state import GameState, claim_once_per_turn
from yasuki_core.engine.rules.stats.card_values import effective_personal_honor
from yasuki_core.game_pieces.cards import L5RCard


# What a card in play gives its controller's Lobby amounts, beyond anything it prints. Shigekawa's
# Court reads "You have a +5 Lobby Bonus"; there is no stat for it, so the grant is text. Keyed by
# printed id like the other registries.
LobbyGrant = Callable[[GameState, L5RCard], int]
LOBBY_BONUSES: HandlerRegistry[LobbyGrant] = HandlerRegistry(
    "lobby bonuses", "already grants a Lobby Bonus"
)
lobby_bonus_grant = LOBBY_BONUSES.make_decorator()


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
        for recorded in game.ongoing
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
LOBBY_BARS: HandlerRegistry[LobbyBar] = HandlerRegistry("lobby bars", "already bars Lobbying")
lobby_bar = LOBBY_BARS.make_decorator()


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
MAY_NOT_LOBBY = FlagRegistry("may not lobby", "already may not be bowed to Lobby")
register_may_not_lobby = MAY_NOT_LOBBY.make_register()


def lobby(game: GameState) -> None:
    """Announce the Lobby ability by asking which Personality it bows. ``legal_actions`` has already
    checked the turn, the honor comparison, and that a Personality is there to pay with."""
    seat = game.active
    game.pending = ChooseLobbyTarget(
        seat=seat,
        candidates=tuple(card.id for card in lobby_candidates(game, seat)),
    )


def apply_lobby_target(
    game: GameState, request: ChooseLobbyTarget, response: DecisionResponse
) -> None:
    """Bow the chosen Personality and take the Imperial Favor.

    ShE datasheet: bowing the Personality is the cost and taking the Favor the effect.

    The Personality is marked as having Lobbied, for the cards that ask who did.
    """
    seat = request.seat
    game.pending = None
    game.use_once(lobby_key(seat, game.turn))
    lobbied = game.table.cards_by_id[response.choices[0]]
    claim_once_per_turn(game, lobbied, LOBBIED_TAG)
    triggers.resolve_effects(game, [Bow(lobbied.id), TakeFavor(seat)])


def lobby_candidates(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The Personalities ``seat`` could bow to Lobby: their own, unbowed, with 1 or more Personal
    Honor, and not one printed "may not Lobby". Zero Personal Honor is the boundary the datasheet
    draws, not merely a floor."""
    return [
        card
        for card in queries.owned_personalities(game, seat)
        if not card.bowed
        and effective_personal_honor(game, card) >= 1
        and card.printed_id not in MAY_NOT_LOBBY
    ]


def lobby_key(seat: PlayerId, turn: int) -> str:
    """The once-per-turn usage key for a seat's Lobby, scoped to the turn the way :func:`legacy_key`
    is.

    Named for the Lobby action rather than for the rulebook ability, because the ShE datasheet caps
    a player at one Lobby action per turn whatever granted it, not at one use of this ability.
    """
    return f"lobby:{seat.name}:{turn}"

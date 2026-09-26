from collections.abc import Callable
from typing import TypeGuard

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board import queries
from yasuki_core.engine.rules.effects import (
    Bow,
    Choose,
    Effect,
    SpendOncePerTurn,
    SpendSeatOncePerTurn,
    TakeFavor,
)
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import Action, ActionTiming, ActivateAbility
from yasuki_core.engine.rules.vocabulary.modifiers import LobbyModifier
from yasuki_core.engine.rules.stats.ongoing_grants import grant_applies
from yasuki_core.engine.registrar import FlagRegistry, HandlerRegistry
from yasuki_core.engine.rules.state import GameState, seat_once_key
from yasuki_core.engine.rules.stats.card_values import effective_personal_honor
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import IMPERIAL_LOBBY_PROXY_ID, ONYX_LOBBY_PROXY_ID, Side
from yasuki_core.game_pieces.prints import RulebookPrint

LOBBY = "lobby"

# The prints each seat's Lobby proxy presents, one per arc family, since the arcs word the ability
# differently. ``rulebook/proxies.py`` deals whichever the active ruleset names.
ONYX_LOBBY_PROXY = RulebookPrint(
    name="Lobby", side=Side.FATE, printed_id=ONYX_LOBBY_PROXY_ID, card_type="Other"
)
IMPERIAL_LOBBY_PROXY = RulebookPrint(
    name="Lobby", side=Side.FATE, printed_id=IMPERIAL_LOBBY_PROXY_ID, card_type="Other"
)


def is_lobby(action: Action) -> TypeGuard[ActivateAbility]:
    """Whether ``action`` takes the Lobby ability on a seat's Lobby proxy."""
    return isinstance(action, ActivateAbility) and action.ability_key == LOBBY


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
    """``amount``, about ``seat``, as a Lobby action reads it. Its Lobby Bonus is included.

    Any amount is adjusted, not only Family Honor: the rulebook Lobby checks Family Honor, but each
    Wind's own Lobby checks something else (cards in hand, the total Gold Cost of attachments
    controlled, the total Force of unbowed Followers and Personalities), and the Bonus applies to
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

    Only what a card forbids. The rulebook's own conditions on Lobbying are checked by each arc's
    Lobby ability.
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
    """The once-per-turn usage key for a seat's Lobby, the one :class:`~.SpendSeatOncePerTurn`
    claims under the ``LOBBY`` tag.

    Named for the Lobby action rather than for the rulebook ability, because the ShE datasheet caps
    a player at one Lobby action per turn whatever granted it, not at one use of this ability. A
    card's own Lobby spends the same tag.
    """
    return seat_once_key(seat, LOBBY, turn)


def has_highest_lobby_honor(game: GameState, seat: PlayerId) -> bool:
    """Whether ``seat``'s Family Honor is higher than each other player's, as a Lobby reads it.

    Both sides of the comparison are read through :func:`~.lobby_amount`, since the datasheet
    adjusts an amount by the Bonuses and Penalties on the player it is about rather than on the
    player acting. A tie does not qualify.
    """
    seats = game.table.seats
    honor = lobby_amount(game, seat, seats[seat].honor)
    return all(
        lobby_amount(game, other, info.honor) < honor
        for other, info in seats.items()
        if other is not seat
    )


def _may_take_lobby(game: GameState, seat: PlayerId) -> bool:
    """What every arc's Lobby asks before anything it prints: nothing in play forbids the seat to
    Lobby, and it has not taken a Lobby action this turn."""
    return may_lobby(game, seat) and not game.has_used(lobby_key(seat, game.turn))


def _lobby_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Spend the seat's Lobby for the turn and bow one of its Personalities. The pick is the cost,
    so a seat with nobody to bow cannot pay and is not offered the action."""
    seat = source.owner
    candidates = tuple(card.id for card in lobby_candidates(game, seat))
    return [
        SpendSeatOncePerTurn(seat=seat, tag=LOBBY),
        Choose(
            seat=seat,
            candidates=candidates,
            minimum=1,
            maximum=1,
            resolver=LOBBY,
            source_id=source.id,
        ),
    ]


@triggers.choice_resolver(LOBBY, prompt="Bow a Personality to Lobby")
def _lobby_bow(
    game: GameState, source_id: str | None, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Bow the chosen Personality, marking it as having Lobbied for the cards that ask who did."""
    return [SpendOncePerTurn(card_id=chosen[0], tag=LOBBIED_TAG), Bow(chosen[0])]


def _onyx_lobby_targets(game: GameState, source: L5RCard) -> list[str]:
    """The proxy itself on the seat's own turn, when the seat's Family Honor is higher than each
    other player's. "If it is your turn" is printed because an Open designator would otherwise let
    another seat's player Lobby."""
    seat = source.owner
    if seat is not game.active or not _may_take_lobby(game, seat):
        return []
    return itself(game, source) if has_highest_lobby_honor(game, seat) else []


def _onyx_lobby_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [TakeFavor(source.owner)]


register_ability(
    ONYX_LOBBY_PROXY_ID,
    Ability(
        timings=(ActionTiming.OPEN,),
        label=(
            "Political Open: If it is your turn and you have higher Family Honor than each other "
            "player, bow your target unbowed Personality with 1 or more Personal Honor to take the "
            "Imperial Favor."
        ),
        cost=_lobby_cost,
        targets=_onyx_lobby_targets,
        effects=_onyx_lobby_effects,
        hits_every_target=True,
        key=LOBBY,
        keywords=frozenset({keywords.POLITICAL}),
        located_at=(CardLocation.RULEBOOK,),
        from_rulebook=True,
    ),
)


def _imperial_lobby_targets(game: GameState, source: L5RCard) -> list[str]:
    """The proxy itself unless the seat already holds the Favor. The pre-Gold rulebook sets no honor
    condition on lobbying, only on its outcome, and there is nothing to lobby for while holding the
    Favor (Official L5R FAQ 3.10)."""
    seat = source.owner
    if game.favor_holder is seat or not _may_take_lobby(game, seat):
        return []
    return itself(game, source)


def _imperial_lobby_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Take the Favor with Family Honor higher than each other player's, and otherwise leave it
    where it is.

    The rulebook opens the lobby to the other players unless the Favor is uncontrolled and the
    lobbying seat's Family Honor is highest, and lets every player bow Personalities and discard a
    card to raise or lower that Family Honor until all pass. Neither contribution is modeled, so the
    lobby resolves as though every player passed at once: the seat takes the Favor only with the
    highest Family Honor.
    """
    seat = source.owner
    return [TakeFavor(seat)] if has_highest_lobby_honor(game, seat) else []


register_ability(
    IMPERIAL_LOBBY_PROXY_ID,
    Ability(
        timings=(ActionTiming.LIMITED,),
        label=(
            "Once per turn, as a Political Limited action, you can lobby for the Imperial Favor. "
            "To do so, bow one of your Personalities with over 0 Personal Honor and announce that "
            "you are lobbying. If no player controls the Imperial Favor and you have more Family "
            "Honor than each other player, you automatically gain the Imperial Favor. No other "
            "players may interfere."
        ),
        cost=_lobby_cost,
        targets=_imperial_lobby_targets,
        effects=_imperial_lobby_effects,
        hits_every_target=True,
        key=LOBBY,
        keywords=frozenset({keywords.POLITICAL}),
        located_at=(CardLocation.RULEBOOK,),
        from_rulebook=True,
    ),
)

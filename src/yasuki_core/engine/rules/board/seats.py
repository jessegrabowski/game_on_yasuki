from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import RULEBOOK_PROXY_IDS
from yasuki_core.game_pieces.prints import FatePrint, StrongholdPrint


def cards_in_play(game: GameState, seat: PlayerId) -> tuple[L5RCard, ...]:
    """The cards ``seat`` controls on the battlefield."""
    return tuple(card for card in game.table.battlefield.cards if card.owner is seat)


def fate_cards_in_play(game: GameState, seat: PlayerId) -> tuple[L5RCard, ...]:
    """The Fate cards ``seat`` controls on the battlefield."""
    return tuple(card for card in cards_in_play(game, seat) if isinstance(card.printed, FatePrint))


def cards_in_hand(game: GameState, seat: PlayerId) -> tuple[L5RCard, ...]:
    """The cards in ``seat``'s hand, as the rules count them. A card announced out of it that has
    not landed is in a resolution or entering-play area instead, and the Imperial Favor's proxy that
    waits there is no card (CR, Resolution Area; CR, The Imperial Favor)."""
    return tuple(
        card
        for card in game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards
        if card.id not in game.announced_from_hand and card.printed_id not in RULEBOOK_PROXY_IDS
    )


def seat_stronghold(game: GameState, seat: PlayerId | None) -> L5RCard | None:
    """``seat``'s Stronghold, or None when it has none in play."""
    for card in game.table.battlefield.cards:
        if card.owner is seat and isinstance(card.printed, StrongholdPrint):
            return card
    return None


def opposing_seats(game: GameState, seat: PlayerId) -> tuple[PlayerId, ...]:
    """Every seat but ``seat``, in table order."""
    return tuple(other for other in game.table.seats if other is not seat)


def went_second(game: GameState, seat: PlayerId) -> bool:
    """Whether ``seat`` did not go first, which several cards condition on."""
    return seat is not game.first_player


def seat_controls_printed(
    game: GameState, seat: PlayerId, keyword: str, *, other_than: L5RCard | None = None
) -> bool:
    """Whether ``seat`` controls an in-play card printing ``keyword``.

    Printed keywords only, where :func:`~yasuki_core.engine.rules.board.queries.has_keyword` reads
    effective ones. A card granting itself a keyword reads its controller's board to decide, so
    answering this from effective keywords would make two such cards ask each other without end --
    Fortified Farmlands is not Unique, and two copies each grant on the other's presence.

    ``other_than`` skips one card, matched by identity, so an "another" clause can exclude the card
    asking. Default None.
    """
    return any(
        keyword in card.keywords and card is not other_than
        for card in game.table.battlefield.cards
        if card.owner is seat
    )


def cards_named(game: GameState, seat: PlayerId, printed_id: str) -> tuple[L5RCard, ...]:
    """The cards ``seat`` controls whose print is ``printed_id`` -- what a card means when it speaks
    about another copy of a named card rather than about a keyword or a type."""
    return tuple(card for card in cards_in_play(game, seat) if card.printed_id == printed_id)

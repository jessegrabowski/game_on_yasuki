from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import StrongholdPrint


def cards_in_play(game: GameState, seat: PlayerId) -> tuple[L5RCard, ...]:
    """The cards ``seat`` controls on the battlefield."""
    return tuple(card for card in game.table.battlefield.cards if card.owner is seat)


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


def seat_controls(
    game: GameState, seat: PlayerId, keyword: str, *, other_than: L5RCard | None = None
) -> bool:
    """Whether ``seat`` controls an in-play card carrying ``keyword``.

    ``other_than`` skips one card, matched by identity, so an "another" clause can exclude the card
    asking. Default None.
    """
    return any(
        keyword in card.keywords and card is not other_than
        for card in game.table.battlefield.cards
        if card.owner is seat
    )

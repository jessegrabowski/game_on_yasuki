import re

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.board.queries import has_keyword
from yasuki_core.engine.rules.board.seats import cards_in_play
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard


def copy_may_enter(game: GameState, seat: PlayerId, card: L5RCard) -> bool:
    """Whether the limits on copies leave ``seat`` free to bring ``card`` into play: Unique, one
    per controller, and Singular, one on the table."""
    return may_enter_as_unique(game, seat, card) and may_enter_as_singular(game, card)


def may_enter_as_unique(game: GameState, seat: PlayerId, card: L5RCard) -> bool:
    """Whether Unique leaves ``seat`` free to bring ``card`` into play: always, unless the card is
    Unique and the seat already controls a Unique card with the same title (CR, Unique).

    The CR's Experienced exception is overlaying, which replaces the lesser version without the
    new card entering play. Overlaying is not modeled, so an Experienced version entering play
    normally is refused like any other copy.
    """
    if not card.printed.is_unique:
        return True
    title = printed_title(card)
    return not any(
        held is not card and held.printed.is_unique and printed_title(held) == title
        for held in cards_in_play(game, seat)
    )


def may_enter_as_singular(game: GameState, card: L5RCard) -> bool:
    """Whether Singular leaves ``card`` free to enter play: always, unless it is Singular and a
    card with the same title is in play under any seat (ShE datasheet, Singular)."""
    if not has_keyword(game, card, keywords.SINGULAR):
        return True
    title = printed_title(card)
    return not any(
        held is not card and printed_title(held) == title for held in game.table.battlefield.cards
    )


# A card id is the slug of its extended title, and the experience qualifier is the tail of that:
# "experienced" or "inexperienced", then an optional level and set code, as in "_experienced_2cw".
_EXPERIENCE_TAIL = re.compile(r"_(?:in)?experienced.*$")


def printed_title(card: L5RCard) -> str:
    """The title ``card`` prints as its id spells it, shared by every experience level of one
    card. A card built without an id, as a test fixture is, reads as its name."""
    if card.printed_id is None:
        return card.name
    return _EXPERIENCE_TAIL.sub("", card.printed_id)

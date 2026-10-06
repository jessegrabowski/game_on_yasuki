import re

from yasuki_core.card_identity import card_slug, experience_alias
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
    own = titles(card)
    return not any(
        held is not card and held.printed.is_unique and titles(held) & own
        for held in cards_in_play(game, seat)
    )


def may_enter_as_singular(game: GameState, card: L5RCard) -> bool:
    """Whether Singular leaves ``card`` free to enter play: always, unless it is Singular and a
    card with the same title is in play under any seat (ShE datasheet, Singular)."""
    if not has_keyword(game, card, keywords.SINGULAR):
        return True
    own = titles(card)
    return not any(held is not card and titles(held) & own for held in game.table.battlefield.cards)


# A print built from no database record has no title: the desktop sandbox's cards, created tokens,
# rulebook proxies, test fixtures and replays logged before titles were. It falls back to its id,
# whose experience qualifier is the tail: "experienced" or "inexperienced", then an optional level
# and set code.
_EXPERIENCE_TAIL = re.compile(r"_(?:in)?experienced.*$")


def titles(card: L5RCard) -> frozenset[str]:
    """The titles ``card`` answers to where the rules compare titles: the title it prints, shared by
    every experience version of one card, and the title an "Experienced [#] Name" keyword names (CR,
    Experienced). Compared as slugs, so case and punctuation do not tell two titles apart."""
    printed = card.printed
    named = {
        card_slug(printed.title) if printed.title else _EXPERIENCE_TAIL.sub("", printed.printed_id)
    }
    if alias := experience_alias(printed.keywords):
        named.add(card_slug(alias))
    return frozenset(named)

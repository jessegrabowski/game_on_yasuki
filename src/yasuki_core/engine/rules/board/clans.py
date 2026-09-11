from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.board.seats import seat_stronghold
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


def seat_alignments(game: GameState, seat: PlayerId | None) -> set[str]:
    """Every Clan Alignment slug ``seat`` plays, taken from its Stronghold. Empty for an unaligned
    seat and for one with no Stronghold in play.

    A set for the same reason :func:`~.card_alignments` is one: a card may print more than one clan,
    and a Stronghold is a card.
    """
    stronghold = seat_stronghold(game, seat)
    return card_alignments(stronghold) if stronghold is not None else set()


def card_alignments(card: L5RCard) -> set[str]:
    """The canonical Clan Alignment slugs ``card`` carries, dropping clan names that are not
    alignments in the active ruleset (minor clans, Shadowlands, "Unaligned", ...). Empty for an
    unaligned card."""
    return {
        slug for name in _clan_names(card) if (slug := ruleset.ACTIVE.alignment(name)) is not None
    }


def seat_alignment_name(game: GameState, seat: PlayerId | None) -> str | None:
    """The clan a card created "with your Clan Alignment" takes: the name printed on ``seat``'s
    Stronghold, or None when that clan is no legal alignment -- an unaligned seat has none to give.

    The printed name rather than :func:`~.seat_alignments`' slug, because the created card carries
    it the way any card carries its clan. The first legal one, for a Stronghold printing several.
    """
    stronghold = seat_stronghold(game, seat)
    if stronghold is None:
        return None
    for name in _clan_names(stronghold):
        if ruleset.ACTIVE.alignment(name) is not None:
            return name
    return None


def _clan_names(card: L5RCard) -> tuple[str, ...]:
    """The card's printed clan names: its :attr:`clans` list, or the lone ``clan`` when that is
    empty."""
    if card.clans:
        return card.clans
    return (card.clan,) if card.clan else ()


def is_clan(game: GameState, seat: PlayerId | None, clan: str) -> bool:
    """Whether ``seat`` plays ``clan``, read from its Stronghold's Clan Alignment."""
    alignment = ruleset.ACTIVE.alignment(clan)
    return alignment is not None and alignment in seat_alignments(game, seat)

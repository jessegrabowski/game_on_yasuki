from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard

# The readers below are views over ``TableState.units``: unit membership, not the presentation
# stacking in ``TableState.attachments``, which carries no rules meaning and which the rules layer
# must never read. The substrate owns the relation and keeps its invariants, so nothing here
# validates or mirrors it. A rules-layer copy would be a desync waiting to happen.


def attached_to(game: GameState, card: L5RCard) -> L5RCard | None:
    """The Personality ``card`` is attached to, or None when it is attached to none.

    Raises
    ------
    KeyError
        If the relation names a Personality that has left the table, which the substrate's own
        bookkeeping rules out. Reading it as "attached to nothing" would hide a broken invariant
        behind the answer an unattached card legitimately gives.
    """
    personality_id = game.table.units.get(card.id)
    if personality_id is None:
        return None
    return game.table.cards_by_id[personality_id]


def attachments_of(game: GameState, card: L5RCard) -> tuple[L5RCard, ...]:
    """The cards attached to ``card``, in the order they were attached. With ``card`` himself, his
    unit (CR, Unit).

    The relation is flat: everything in a unit attaches to the Personality, however the table
    renders it, so there is no chain to walk. The order is the relation's insertion order, which
    replay reproduces.
    """
    return tuple(
        game.table.cards_by_id[member]
        for member, personality_id in game.table.units.items()
        if personality_id == card.id
    )


def unit_of(game: GameState, card: L5RCard) -> tuple[L5RCard, ...]:
    """``card`` and the cards attached to him, in attach order: his unit (CR, Unit). A card with
    nothing attached is a unit of one, so a caller need not ask whether it is a Personality.

    Read the unit before moving the card: leaving the battlefield clears the relation, so a caller
    that moves first finds a unit of one.
    """
    return (card, *attachments_of(game, card))


def shares_unit(game: GameState, card: L5RCard, other: L5RCard) -> bool:
    """Whether ``card`` and ``other`` stand in the same unit (CR, Unit). A card shares a unit with
    itself, so a text about "cards in this unit" covers the card it is printed on."""
    return other in unit_of(game, attached_to(game, card) or card)

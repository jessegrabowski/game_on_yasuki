from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard

# The two readers below are views over ``TableState.attachments``. The substrate owns the graph and
# keeps its invariants — a child is always a battlefield card, a parent is a battlefield card or a
# Province, and no chain of parents loops — so nothing here validates or mirrors it. A rules-layer
# copy would be a desync waiting to happen.


def attached_to(game: GameState, card: L5RCard) -> L5RCard | None:
    """The card ``card`` hangs on, or None when it hangs on nothing.

    A Fortification or Region attached to a Province also reads None: the question this answers is
    which *card* carries it, and a Province is not one.
    """
    parent = game.table.attachments.get(card.id)
    if not isinstance(parent, str):
        return None
    return game.table.cards_by_id.get(parent)


def attachments_of(game: GameState, card: L5RCard) -> tuple[L5RCard, ...]:
    """The cards attached directly to ``card``, in the order they were attached.

    Direct only: an Item attached to a Follower is the Follower's, not the Personality's. The order
    is the graph's insertion order, which replay reproduces.
    """
    return tuple(
        game.table.cards_by_id[child]
        for child, parent in game.table.attachments.items()
        if parent == card.id
    )

from collections.abc import Callable

from yasuki_core.engine.rules.modifiers import Stat
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


# What an attachment grants the card it hangs on, beyond the modifier it prints. Haramaki-do prints
# +2F and says "This Personality has +1PH" in its text; the printed half is a stat on the print, the
# written half is this. Keyed by printed id like the other per-card registries.
GrantHandler = Callable[[GameState, L5RCard, L5RCard], dict[Stat, int]]
ATTACHMENT_GRANTS: dict[str, GrantHandler] = {}


def attachment_grant(printed_id: str) -> Callable[[GrantHandler], GrantHandler]:
    """Register the decorated function as ``printed_id``'s grant to the card it attaches to."""

    def register(handler: GrantHandler) -> GrantHandler:
        if printed_id in ATTACHMENT_GRANTS:
            raise ValueError(f"{printed_id} already has an attachment grant")
        ATTACHMENT_GRANTS[printed_id] = handler
        return handler

    return register


def granted_stat(game: GameState, attached: L5RCard, host: L5RCard, stat: Stat) -> int:
    """What ``attached``'s own text gives ``host`` for ``stat``, or 0 when it gives nothing."""
    handler = ATTACHMENT_GRANTS.get(attached.printed_id)
    if handler is None:
        return 0
    return handler(game, attached, host).get(stat, 0)

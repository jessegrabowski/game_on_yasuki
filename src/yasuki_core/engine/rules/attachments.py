from collections.abc import Callable

from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard

# The readers below are views over ``TableState.units`` — unit membership, not the presentation
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
    """The cards attached to ``card``, in the order they were attached — with ``card`` himself, his
    unit (CR, Unit).

    The relation is flat: everything in a unit attaches to the Personality, however the table renders
    it, so there is no chain to walk. The order is the relation's insertion order, which replay
    reproduces.
    """
    return tuple(
        game.table.cards_by_id[member]
        for member, personality_id in game.table.units.items()
        if personality_id == card.id
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

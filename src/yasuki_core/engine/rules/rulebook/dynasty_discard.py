from yasuki_core.engine import ops
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.board.queries import province_key_holding
from yasuki_core.engine.rules.events import CardDiscarded
from yasuki_core.engine.rules.turn.provinces import defer_refill
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import ZoneKey, ZoneRole


def dynasty_discard(game: GameState, card_id: str) -> None:
    """Discard a face-up province card to its owner's dynasty discard and refill the province — the
    Dynasty Discard action. It has no cost, so it resolves at once with no payment."""
    card = game.table.cards_by_id[card_id]
    seat = card.owner
    province_key = province_key_holding(game, seat, card_id)
    ops.move_card(game.table, card, ZoneKey(seat, ZoneRole.DYNASTY_DISCARD))
    if province_key is not None:
        defer_refill(game, province_key)
    triggers.fire(game, CardDiscarded(card_id, card.side, seat))

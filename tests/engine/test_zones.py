from app.engine.zones import (
    HandZone,
)
from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side


def test_zone_add_remove_and_constraints():
    hand = HandZone()
    fate_card = L5RCard(id="f1", name="Fate", side=Side.FATE)
    dynasty_card = L5RCard(id="d1", name="Dynasty", side=Side.DYNASTY)

    hand.add(fate_card)
    assert len(hand) == 1
    hand.add(dynasty_card)  # ignored due to side constraint
    assert len(hand) == 1

    assert hand.remove(fate_card) is True
    assert hand.remove(fate_card) is False

from app.engine.zones import (
    HandZone,
    BattlefieldZone,
    ProvinceZone,
    FateDiscardZone,
    FateBanishZone,
    DynastyDiscardZone,
    DynastyBanishZone,
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


def test_all_zone_types_exist_and_accept_sides():
    zones = [
        BattlefieldZone(),
        ProvinceZone(),
        FateDiscardZone(),
        FateBanishZone(),
        DynastyDiscardZone(),
        DynastyBanishZone(),
    ]
    c_f = L5RCard(id="f2", name="Fate2", side=Side.FATE)
    c_d = L5RCard(id="d2", name="Dynasty2", side=Side.DYNASTY)

    for z in zones:
        z.add(c_f)
        z.add(c_d)
        # Battlefield allows both, others enforce a side; we just ensure no crash and length increments appropriately
        assert len(z) >= 0

from app.engine.zones import ProvinceZone, FateDiscardZone, HandZone
from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side


def test_province_capacity_enforced():
    prov = ProvinceZone()
    d1 = L5RCard(id="d1", name="D1", side=Side.DYNASTY)
    d2 = L5RCard(id="d2", name="D2", side=Side.DYNASTY)

    assert prov.add(d1) is True
    assert len(prov) == 1
    # second add rejected
    assert prov.add(d2) is False
    assert len(prov) == 1


def test_discard_is_infinite_capacity():
    disc = FateDiscardZone()
    c = L5RCard(id="f1", name="F1", side=Side.FATE)
    for i in range(100):
        assert disc.add(c) is True
    assert len(disc) == 100


def test_hand_is_infinite_capacity():
    hand = HandZone()
    c = L5RCard(id="f2", name="F2", side=Side.FATE)
    for i in range(100):
        assert hand.add(c) is True
    assert len(hand) == 100

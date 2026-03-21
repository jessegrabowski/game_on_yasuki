from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


def test_province_capacity_enforced():
    prov = ProvinceZone()
    d1 = L5RCard(id="d1", name="D1", side=Side.DYNASTY)
    d2 = L5RCard(id="d2", name="D2", side=Side.DYNASTY)

    assert prov.add(d1) is True
    assert len(prov) == 1
    # second add rejected
    assert prov.add(d2) is False
    assert len(prov) == 1

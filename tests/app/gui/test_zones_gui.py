from app.gui.field import GameField
from app.engine.zones import HandZone, ProvinceZone


def test_zone_rendering(root):
    field = GameField(root, width=600, height=400)
    field.pack()
    root.update_idletasks()
    root.update()

    hand = HandZone()
    prov = ProvinceZone()

    hand_tag = field.add_zone(hand, x=100, y=100, w=200, h=120)
    prov_tag = field.add_zone(prov, x=500, y=300, w=200, h=120)

    # Each zone should create at least one canvas item with its tag
    assert field.find_withtag(hand_tag)
    assert field.find_withtag(prov_tag)

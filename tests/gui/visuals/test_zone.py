import tkinter as tk

from app.gui.visuals.zone import ZoneVisual
from app.engine.zones import HandZone, ProvinceZone
from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side


def test_zone_bbox_and_empty_draw(root):
    z = HandZone()
    zv = ZoneVisual(z, x=150, y=140, w=120, h=80, tag="zone:1")
    assert zv.size == (120, 80)
    assert zv.bbox == (150 - 60, 140 - 40, 150 + 60, 140 + 40)

    cv = tk.Canvas(root, width=300, height=300)
    cv.pack()
    root.update_idletasks()
    root.update()

    before = len(cv.find_withtag("zone:1"))
    zv.draw(cv)
    after = len(cv.find_withtag("zone:1"))
    assert after >= before + 2  # rect + text for empty


def test_zone_draw_with_top_card_front_and_back(root):
    cv = tk.Canvas(root, width=300, height=300)
    cv.pack()
    root.update_idletasks()
    root.update()

    # Face-up card uses front image; we don't assert image presence, only items drawn
    z1 = ProvinceZone()
    c1 = L5RCard(id="z1", name="Z1", side=Side.DYNASTY)
    z1.add(c1)
    zv1 = ZoneVisual(z1, x=80, y=80, w=120, h=80, tag="zone:2")
    zv1.draw(cv)
    assert cv.find_withtag("zone:2")

    # Face-down card uses back image
    z2 = ProvinceZone()
    c2 = L5RCard(id="z2", name="Z2", side=Side.DYNASTY)
    c2.turn_face_down()
    z2.add(c2)
    zv2 = ZoneVisual(z2, x=200, y=80, w=120, h=80, tag="zone:3")
    zv2.draw(cv)
    assert cv.find_withtag("zone:3")

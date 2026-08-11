import tkinter as tk

from yasuki_gui import theme
from yasuki_gui.visuals.zone import ZoneVisual
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import CardPrint
from yasuki_core.engine.players import PlayerId


def _outlines(canvas: tk.Canvas, tag: str) -> list[str]:
    """The outline colors of the rectangles drawn under ``tag``."""
    return [
        canvas.itemcget(item, "outline")
        for item in canvas.find_withtag(tag)
        if canvas.type(item) == "rectangle"
    ]


def test_zone_bbox_and_empty_draw(root):
    zv = ZoneVisual(
        [], is_province=False, name="Fate Discard", x=150, y=140, w=120, h=80, tag="zone:1"
    )
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


def test_a_province_card_picked_for_a_decision_is_ringed(root):
    # Provinces are what Cycle asks the player to click, and an unringed one leaves them with no
    # way to tell what they have picked.
    cv = tk.Canvas(root, width=300, height=300)
    cv.pack()
    root.update_idletasks()
    root.update()

    card = L5RCard.of(CardPrint, id="z9", name="Z9", side=Side.DYNASTY, owner=PlayerId.P1)
    zv = ZoneVisual([card], True, "Province", 80, 80, 120, 80, "zone:picked", selected_ids=["z9"])

    zv.draw(cv)

    assert theme.SELECT in _outlines(cv, "zone:picked")


def test_an_unpicked_province_card_keeps_its_ordinary_border(root):
    cv = tk.Canvas(root, width=300, height=300)
    cv.pack()
    root.update_idletasks()
    root.update()

    card = L5RCard.of(CardPrint, id="z8", name="Z8", side=Side.DYNASTY, owner=PlayerId.P1)
    zv = ZoneVisual([card], True, "Province", 80, 80, 120, 80, "zone:plain", selected_ids=["z9"])

    zv.draw(cv)

    outlines = _outlines(cv, "zone:plain")
    assert theme.SELECT not in outlines
    assert theme.CARD_BORDER in outlines


def test_zone_draw_with_top_card_front_and_back(root):
    cv = tk.Canvas(root, width=300, height=300)
    cv.pack()
    root.update_idletasks()
    root.update()

    # Face-up card uses front image; we don't assert image presence, only items drawn
    c1 = L5RCard.of(CardPrint, id="z1", name="Z1", side=Side.DYNASTY, owner=PlayerId.P1)
    zv1 = ZoneVisual([c1], is_province=True, name="Province", x=80, y=80, w=120, h=80, tag="zone:2")
    zv1.draw(cv)
    assert cv.find_withtag("zone:2")

    # Face-down card uses back image
    c2 = L5RCard.of(CardPrint, id="z2", name="Z2", side=Side.DYNASTY, owner=PlayerId.P1)
    c2.turn_face_down()
    zv2 = ZoneVisual(
        [c2], is_province=True, name="Province", x=200, y=80, w=120, h=80, tag="zone:3"
    )
    zv2.draw(cv)
    assert cv.find_withtag("zone:3")

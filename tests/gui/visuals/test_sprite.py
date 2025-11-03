from app.gui.visuals.sprite import CardSpriteVisual
from app.gui.visuals.visual import MarqueeBoxVisual
from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side
import tkinter as tk


def test_size_and_bbox_flip_with_bowed(root):
    c = L5RCard(id="s1", name="Sprite", side=Side.FATE)
    sv = CardSpriteVisual(c, x=100, y=100, tag="card:1")
    w, h = sv.size
    assert w > 0 and h > 0
    assert sv.bbox == (100 - w // 2, 100 - h // 2, 100 + w // 2, 100 + h // 2)

    c.bow()
    w2, h2 = sv.size
    assert (w2, h2) == (h, w)  # swapped when bowed


def test_draw_creates_canvas_items(root):
    c = L5RCard(id="s2", name="SpriteDraw", side=Side.DYNASTY)
    sv = CardSpriteVisual(c, x=80, y=60, tag="card:2")
    _ = root.nametowidget(root._w)  # root is a Tk; but we need a Canvas to draw on

    cv = tk.Canvas(root, width=200, height=200)
    cv.pack()
    root.update_idletasks()
    root.update()

    before = len(cv.find_withtag("card:2"))
    sv.draw(cv, selected=True)
    after = len(cv.find_withtag("card:2"))
    assert after >= before + 1

    # Intersects against a marquee covering the sprite center
    rect = MarqueeBoxVisual((sv.x - 1, sv.y - 1, sv.x + 1, sv.y + 1))
    assert sv.intersects(rect)

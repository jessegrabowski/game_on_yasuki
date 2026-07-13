from yasuki_gui.visuals.sprite import CardSpriteVisual
from yasuki_gui.visuals.visual import MarqueeBoxVisual
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import ALL_COUNTERS
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


def test_wealth_counter_draws_a_badge(root):
    cv = tk.Canvas(root, width=200, height=200)
    cv.pack()
    root.update_idletasks()

    plain = L5RCard(id="p1", name="Plain", side=Side.DYNASTY)
    CardSpriteVisual(plain, x=60, y=60, tag="card:p").draw(cv)
    assert cv.find_withtag("card:p:counter") == ()  # no counters, no badge

    rich = L5RCard(id="w1", name="Rice Farm", side=Side.DYNASTY, counters={"wealth": 2})
    CardSpriteVisual(rich, x=140, y=60, tag="card:w").draw(cv)
    assert cv.find_withtag("card:w:counter")  # the wealth badge (disc + count) is drawn


def test_each_counter_kind_draws_a_distinctly_coloured_badge(root):
    cv = tk.Canvas(root, width=200, height=200)
    cv.pack()
    root.update_idletasks()

    card = L5RCard(id="c1", name="C", side=Side.DYNASTY, counters={c.key: 1 for c in ALL_COUNTERS})
    CardSpriteVisual(card, x=100, y=100, tag="card:c").draw(cv)

    discs = [i for i in cv.find_withtag("card:c:counter") if cv.type(i) == "oval"]
    distinct_colours = {cv.itemcget(disc, "fill") for disc in discs}
    assert len(discs) == len(ALL_COUNTERS)  # one badge per kind on the card
    assert len(distinct_colours) == len(ALL_COUNTERS)  # each kind a distinct colour, none alike

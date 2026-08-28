from yasuki_gui.visuals.sprite import CardSpriteVisual
from yasuki_gui.visuals.visual import MarqueeBoxVisual
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import CardPrint, PersonalityPrint
from yasuki_core.engine.rules.modifiers import Stat
import tkinter as tk
from yasuki_core.engine.players import PlayerId


def test_size_and_bbox_flip_with_bowed(root):
    c = L5RCard.of(CardPrint, id="s1", name="Sprite", side=Side.FATE, owner=PlayerId.P1)
    sv = CardSpriteVisual(c, x=100, y=100, tag="card:1")
    w, h = sv.size
    assert w > 0 and h > 0
    assert sv.bbox == (100 - w // 2, 100 - h // 2, 100 + w // 2, 100 + h // 2)

    c.bow()
    w2, h2 = sv.size
    assert (w2, h2) == (h, w)  # swapped when bowed


def test_draw_creates_canvas_items(root):
    c = L5RCard.of(CardPrint, id="s2", name="SpriteDraw", side=Side.DYNASTY, owner=PlayerId.P1)
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

    plain = L5RCard.of(CardPrint, id="p1", name="Plain", side=Side.DYNASTY, owner=PlayerId.P1)
    CardSpriteVisual(plain, x=60, y=60, tag="card:p").draw(cv)
    assert cv.find_withtag("card:p:counter") == ()  # no counters, no badge

    rich = L5RCard.of(
        CardPrint,
        id="w1",
        name="Rice Farm",
        side=Side.DYNASTY,
        counters={"wealth": 2},
        owner=PlayerId.P1,
    )
    CardSpriteVisual(rich, x=140, y=60, tag="card:w").draw(cv)
    assert cv.find_withtag("card:w:counter")  # the wealth badge (disc + count) is drawn


def test_styled_counters_draw_their_own_colours(root):
    cv = tk.Canvas(root, width=200, height=200)
    cv.pack()
    root.update_idletasks()

    # Wealth and Sincerity carry hand-picked badge styles, so a card holding both reads them apart.
    card = L5RCard.of(
        CardPrint,
        id="c1",
        name="C",
        side=Side.DYNASTY,
        counters={"wealth": 1, "sincerity": 2},
        owner=PlayerId.P1,
    )
    CardSpriteVisual(card, x=100, y=100, tag="card:c").draw(cv)

    discs = [i for i in cv.find_withtag("card:c:counter") if cv.type(i) == "oval"]
    assert len(discs) == 2  # one badge per counter kind on the card
    assert len({cv.itemcget(disc, "fill") for disc in discs}) == 2  # the two styles differ


def test_badges_scale_with_the_cards_counters_not_the_catalogue(root):
    cv = tk.Canvas(root, width=200, height=200)
    cv.pack()
    root.update_idletasks()

    # A card with three counters draws three badges — rendering tracks the card's own tallies, not
    # the 100+-entry counter catalogue.
    card = L5RCard.of(
        CardPrint,
        id="c2",
        name="C",
        side=Side.DYNASTY,
        counters={"fire": 1, "poison": 3, "wealth": 2},
        owner=PlayerId.P1,
    )
    CardSpriteVisual(card, x=100, y=100, tag="card:d").draw(cv)
    discs = [i for i in cv.find_withtag("card:d:counter") if cv.type(i) == "oval"]
    assert len(discs) == 3


def _stamped(canvas, tag):
    """The numbers stamped on the sprite tagged ``tag``."""
    return sorted(
        canvas.itemcget(i, "text")
        for i in canvas.find_withtag(f"{tag}:stat")
        if canvas.type(i) == "text"
    )


def test_a_sprite_stamps_the_stats_it_was_given(root):
    cv = tk.Canvas(root, width=200, height=200)
    hero = L5RCard.of(
        PersonalityPrint, id="h", name="Hero", side=Side.DYNASTY, owner=PlayerId.P1, force=3, chi=4
    )

    CardSpriteVisual(hero, x=100, y=100, tag="card:h", stats={"h": {Stat.FORCE: 7}}).draw(cv)

    assert _stamped(cv, "card:h") == ["4", "7"]


def test_refreshing_a_face_replaces_the_stamps_rather_than_adding_to_them(root):
    """`refresh_face_state` erases its layers by name, so a layer left off that list survives the
    redraw — and a Personality whose Force just changed would carry both numbers at once."""
    cv = tk.Canvas(root, width=200, height=200)
    hero = L5RCard.of(
        PersonalityPrint, id="h", name="Hero", side=Side.DYNASTY, owner=PlayerId.P1, force=3, chi=4
    )
    sprite = CardSpriteVisual(hero, x=100, y=100, tag="card:h")
    sprite.draw(cv)

    sprite.stats = {"h": {Stat.FORCE: 9}}
    sprite.refresh_face_state(cv)

    assert _stamped(cv, "card:h") == ["4", "9"]

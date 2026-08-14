import tkinter as tk

from yasuki_core.engine.players import PlayerId
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import CardPrint
from yasuki_gui.visuals.visual import MarqueeBoxVisual, draw_counter_badges


class TestMarqueeBoxVisual:
    def test_size_and_bbox(self):
        m = MarqueeBoxVisual((10, 20, 30, 50))
        assert m.size == (20, 30)
        assert m.bbox == (10, 20, 30, 50)

    def test_intersects_true_and_false(self):
        a = MarqueeBoxVisual((0, 0, 100, 100))
        b = MarqueeBoxVisual((50, 50, 150, 150))
        c = MarqueeBoxVisual((110, 110, 200, 200))
        assert a.intersects(b) and b.intersects(a)
        assert not a.intersects(c)
        assert not c.intersects(a)


class TestCounterBadges:
    """The badge drawing both the in-play sprite and the Province zone share."""

    def _card(self, **counters):
        return L5RCard.of(
            CardPrint,
            id="c",
            name="C",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            counters=counters or {},
        )

    def test_badges_hang_off_the_cards_top_right_corner(self, root):
        """The bbox is (x0, y0, x1, y1); reading its corners in the wrong order would park the
        badges on the opposite side of the card with every count still correct."""
        canvas = tk.Canvas(root, width=400, height=400)
        draw_counter_badges(canvas, self._card(wealth=1), (100, 40, 220, 200), ("badge",))

        (x0, y0, x1, y1) = canvas.bbox("badge")
        assert x1 <= 220 and x0 > (100 + 220) // 2  # in the right-hand half, inside the card
        assert y0 >= 40 and y1 < (40 + 200) // 2  # in the top half

    def test_each_counter_kind_stacks_its_own_badge_downward(self, root):
        canvas = tk.Canvas(root, width=400, height=400)
        draw_counter_badges(canvas, self._card(wealth=1, sincerity=2), (0, 0, 120, 200), ("badge",))

        discs = [i for i in canvas.find_withtag("badge") if canvas.type(i) == "oval"]
        assert len(discs) == 2
        centres = sorted(canvas.coords(disc)[1] for disc in discs)
        assert centres[1] > centres[0]  # the second badge sits below the first
        assert len({canvas.itemcget(disc, "fill") for disc in discs}) == 2  # styled apart

    def test_a_counter_at_zero_draws_nothing(self, root):
        """A counter spent down to zero leaves its key behind; a badge reading 0 would be noise."""
        canvas = tk.Canvas(root, width=400, height=400)
        draw_counter_badges(canvas, self._card(wealth=0), (0, 0, 120, 200), ("badge",))

        assert canvas.find_withtag("badge") == ()

    def test_a_card_with_no_counters_attribute_is_skipped(self, root):
        """A redacted back has no counters at all, and must draw rather than raise."""
        canvas = tk.Canvas(root, width=400, height=400)
        draw_counter_badges(canvas, object(), (0, 0, 120, 200), ("badge",))

        assert canvas.find_withtag("badge") == ()

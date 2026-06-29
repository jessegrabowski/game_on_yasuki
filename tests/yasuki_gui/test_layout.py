from yasuki_core.engine.table import BoardPos
from yasuki_gui.constants import CARD_W
from yasuki_gui.layout import (
    from_canvas,
    home_slot,
    province_positions,
    to_canvas,
)

W, H = 1000, 800


class TestProjection:
    def test_identity_when_not_flipped(self):
        assert to_canvas(BoardPos(120, 240), flipped=False, canvas_w=W, canvas_h=H) == (120, 240)

    def test_flip_rotates_about_center(self):
        assert to_canvas(BoardPos(120, 240), flipped=True, canvas_w=W, canvas_h=H) == (880, 560)

    def test_round_trips_both_orientations(self):
        for flipped in (False, True):
            pos = from_canvas(310, 420, flipped=flipped, canvas_w=W, canvas_h=H)
            assert to_canvas(pos, flipped=flipped, canvas_w=W, canvas_h=H) == (310, 420)


class TestProvincePositions:
    def test_empty_when_no_provinces(self):
        assert province_positions(W, H, 0, seat_at_bottom=True) == []

    def test_centered_and_evenly_spaced(self):
        xs = [x for x, _ in province_positions(W, H, 4, seat_at_bottom=True)]
        assert sorted(xs) == xs  # left to right
        gaps = {b - a for a, b in zip(xs, xs[1:])}
        assert gaps == {CARD_W}
        assert abs(sum(xs) / len(xs) - W / 2) <= 1  # centred about the canvas (within rounding)

    def test_top_seat_mirrors_column_order(self):
        bottom = province_positions(W, H, 4, seat_at_bottom=True)
        top = province_positions(W, H, 4, seat_at_bottom=False)
        assert [x for x, _ in top] == [x for x, _ in reversed(bottom)]


class TestHomeRow:
    def test_steps_right_by_a_card_width_in_the_bottom_half(self):
        x0, y0 = home_slot(W, H, 0, seat_at_bottom=True)
        x1, y1 = home_slot(W, H, 1, seat_at_bottom=True)
        assert x1 - x0 == CARD_W  # the next home card sits one width to the right
        assert y0 == y1 > H // 2  # the bottom seat's home row is below the midline

    def test_top_seat_home_row_is_above_the_midline(self):
        _, y = home_slot(W, H, 0, seat_at_bottom=False)
        assert y < H // 2

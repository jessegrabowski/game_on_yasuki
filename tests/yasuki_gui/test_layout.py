from yasuki_core.engine.table import BoardPos
from yasuki_gui.constants import CARD_W
from yasuki_gui.layout import (
    card_view_placement,
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


def test_card_view_sits_to_the_right_of_a_left_side_card():
    left, top = card_view_placement(100, 300, 81, 115, 243, 345, 1000, 700)
    assert left == 100 + 81 // 2 + 10  # right edge of the card + gap
    assert top == 300 - 345 // 2  # vertically centred on the card


def test_card_view_flips_left_when_it_would_overflow_the_right_edge():
    left, _ = card_view_placement(950, 300, 81, 115, 243, 345, 1000, 700)
    assert left == 950 - 81 // 2 - 10 - 243  # placed to the card's left instead


def test_card_view_clamps_down_from_the_top_edge():
    _, top = card_view_placement(100, 10, 81, 115, 243, 345, 1000, 700)
    assert top == 0  # a preview taller than the card's top margin is pushed on-screen


def test_card_view_clamps_up_from_the_bottom_edge():
    _, top = card_view_placement(100, 690, 81, 115, 243, 345, 1000, 700)
    assert top == 700 - 345  # a preview past the bottom edge is pulled up to sit fully on-canvas

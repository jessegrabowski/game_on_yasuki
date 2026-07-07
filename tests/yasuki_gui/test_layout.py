from yasuki_core.engine.table import BoardPos
from yasuki_gui.constants import CARD_W
from yasuki_gui.layout import (
    card_view_placement,
    divider_y,
    from_canvas,
    home_slot,
    home_stack_positions,
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


def test_home_stack_gives_distinct_cards_their_own_columns():
    pos = home_stack_positions(
        [("a", "k1"), ("b", "k2")], 1000, 700, seat_at_bottom=True, offset=26
    )
    assert pos["a"][0] != pos["b"][0]  # distinct group keys sit in different columns
    assert pos["a"][1] == pos["b"][1]  # both on the home row (neither is a copy)


def test_home_stack_stacks_copies_down_a_single_column():
    pos = home_stack_positions(
        [("c1", "farm"), ("c2", "farm"), ("c3", "farm")], 1000, 700, seat_at_bottom=True, offset=26
    )
    assert len({p[0] for p in pos.values()}) == 1  # copies share one column
    ys = [pos["c1"][1], pos["c2"][1], pos["c3"][1]]
    assert ys[1] - ys[0] == 26 and ys[2] - ys[1] == 26  # each copy steps down by the offset


def test_home_stack_mixes_distinct_cards_and_interleaved_copies():
    # The real case: a stronghold, a farm, another holding, then a second farm placed together.
    pos = home_stack_positions(
        [("sh", "stronghold"), ("f1", "farm"), ("m1", "market"), ("f2", "farm")],
        1000,
        700,
        seat_at_bottom=True,
        offset=26,
    )
    cols = {card_id: xy[0] for card_id, xy in pos.items()}
    assert cols["sh"] != cols["f1"] != cols["m1"]  # three distinct holdings, three columns
    assert cols["f2"] == cols["f1"]  # a later farm rejoins the farm column, not a fresh one
    assert pos["f2"][1] - pos["f1"][1] == 26  # and stacks one offset below the first


def test_holdings_row_sits_between_the_divider_and_the_provinces():
    h = 800
    holding_y = home_slot(1000, h, 0, seat_at_bottom=True)[1]
    province_y = province_positions(1000, h, 1, seat_at_bottom=True)[0][1]
    # Bottom-to-top the human's rows run provinces, holdings, (reserved personalities), divider.
    assert divider_y(h) < holding_y < province_y

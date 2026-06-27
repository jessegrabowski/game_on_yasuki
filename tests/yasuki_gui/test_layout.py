from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import BoardPos, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_gui.constants import CARD_W
from yasuki_gui.layout import (
    deck_pos,
    from_canvas,
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
        assert sum(xs) // len(xs) == W // 2  # symmetric about the centre

    def test_top_seat_mirrors_column_order(self):
        bottom = province_positions(W, H, 4, seat_at_bottom=True)
        top = province_positions(W, H, 4, seat_at_bottom=False)
        assert [x for x, _ in top] == [x for x, _ in reversed(bottom)]


class TestDeckPositions:
    def test_bottom_seat_has_dynasty_left_fate_right(self):
        dyn_x, _ = deck_pos(W, H, DeckKey(PlayerId.P1, Side.DYNASTY), seat_at_bottom=True)
        fate_x, _ = deck_pos(W, H, DeckKey(PlayerId.P1, Side.FATE), seat_at_bottom=True)
        assert dyn_x < fate_x

    def test_top_seat_mirrors_bottom(self):
        dyn_bottom, _ = deck_pos(W, H, DeckKey(PlayerId.P1, Side.DYNASTY), seat_at_bottom=True)
        dyn_top, _ = deck_pos(W, H, DeckKey(PlayerId.P2, Side.DYNASTY), seat_at_bottom=False)
        assert dyn_bottom + dyn_top == W

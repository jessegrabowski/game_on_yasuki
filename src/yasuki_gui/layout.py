from yasuki_core.engine.table import BoardPos
from yasuki_gui.constants import CARD_W

# How far each seat's province row sits from its edge. The human band (bottom) leaves room for the
# hand strip below it; the opponent (top) draws no hand, so its provinces tuck right up against the
# edge to free the centre. Decks, discards, and banishes live in the off-board info panels.
_PROVINCE_INSET_BOTTOM = 200
_PROVINCE_INSET_TOP = 110
_HAND_INSET = 60


def _row_y(canvas_h: int, seat_at_bottom: bool) -> int:
    return canvas_h - _PROVINCE_INSET_BOTTOM if seat_at_bottom else _PROVINCE_INSET_TOP


def _hand_y(canvas_h: int, seat_at_bottom: bool) -> int:
    return canvas_h - _HAND_INSET if seat_at_bottom else _HAND_INSET


def hand_box(canvas_w: int, canvas_h: int, *, seat_at_bottom: bool) -> tuple[int, int, int, int]:
    """Screen box for a seat's hand strip, spanning most of the canvas width."""
    return canvas_w // 2, _hand_y(canvas_h, seat_at_bottom), canvas_w - 200, 120


def province_positions(
    canvas_w: int, canvas_h: int, count: int, *, seat_at_bottom: bool
) -> list[tuple[int, int]]:
    """Centre points for ``count`` provinces, centre-justified across the canvas on the seat's row.

    The columns are evenly spaced by one card width and reversed for the top seat so its leftmost
    province faces the same edge as the bottom seat's.
    """
    if count <= 0:
        return []
    y = _row_y(canvas_h, seat_at_bottom)
    center_x = canvas_w // 2
    offsets = [(i - (count - 1) / 2) * CARD_W for i in range(count)]
    if not seat_at_bottom:
        offsets.reverse()
    return [(int(center_x + off), y) for off in offsets]


# Where a seat's home row of unplaced cards (its stronghold, sensei, and freshly recruited holdings)
# begins, and how its cards step rightward. The stronghold sits first, so everything that joins it
# later lands beside it.
_HOME_X0 = CARD_W
_HOME_STEP = CARD_W


def home_slot(canvas_w: int, canvas_h: int, index: int, *, seat_at_bottom: bool) -> tuple[int, int]:
    """Position for the ``index``-th unplaced card in a seat's home row, laid left to right from
    inside the seat's edge. The stronghold, sensei, and freshly recruited holdings park here in
    battlefield order until a drag gives them a board spot."""
    y = int(canvas_h * 0.66) if seat_at_bottom else int(canvas_h * 0.34)
    return _HOME_X0 + index * _HOME_STEP, y


def to_canvas(pos: BoardPos, *, flipped: bool, canvas_w: int, canvas_h: int) -> tuple[int, int]:
    """Project a seat-neutral battlefield position to canvas pixels.

    Identity for the human-at-bottom view; a 180° rotation about the canvas centre for the debug
    other-seat view. ``to_canvas`` and :func:`from_canvas` are mutual inverses, so a drag
    round-trips.
    """
    x, y = int(pos.x), int(pos.y)
    if flipped:
        return canvas_w - x, canvas_h - y
    return x, y


def from_canvas(x: int, y: int, *, flipped: bool, canvas_w: int, canvas_h: int) -> BoardPos:
    """Invert :func:`to_canvas`, turning a canvas pixel back into a seat-neutral position."""
    if flipped:
        return BoardPos(float(canvas_w - x), float(canvas_h - y))
    return BoardPos(float(x), float(y))

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import BoardPos
from yasuki_core.game_pieces.constants import Side
from yasuki_gui.constants import CARD_W

# How far a seat's province row sits from the top or bottom edge, and how far the hand sits beyond
# that. The human seat occupies the bottom band; the opponent mirrors it across the top. Decks,
# discards, and banishes live in the off-board info panels, so only the in-play rows go here.
_ROW_INSET = 200
_HAND_INSET = 60


def _row_y(canvas_h: int, seat_at_bottom: bool) -> int:
    return canvas_h - _ROW_INSET if seat_at_bottom else _ROW_INSET


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


def unplaced_battlefield_pos(
    canvas_w: int, canvas_h: int, side: Side, owner: PlayerId | None, *, seat_at_bottom: bool
) -> tuple[int, int]:
    """Where a battlefield card with no real position (the unplaced sentinel — e.g. a freshly
    recruited card) is parked: a staging spot in its owner's half, fate to the left and dynasty to
    the right, set between the midline and the province row so it reads as in play but unplaced."""
    y = int(canvas_h * 0.66) if seat_at_bottom else int(canvas_h * 0.34)
    x = canvas_w // 4 if side is Side.FATE else canvas_w * 3 // 4
    return x, y


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

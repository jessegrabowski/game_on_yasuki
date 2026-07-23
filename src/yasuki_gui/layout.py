from yasuki_core.engine.table import BoardPos
from yasuki_gui.constants import CARD_H, CARD_W

# How far each seat's province row sits from its edge. The human band (bottom) leaves room for the
# hand strip below it; the opponent (top) draws no hand, so its provinces tuck right up against the
# edge to free the centre. Decks, discards, and banishes live in the off-board info panels.
_PROVINCE_INSET_BOTTOM = 165
_PROVINCE_INSET_TOP = 55
# The hand's centre; its cards reach CARD_H/2 below it, so this is as low as the strip goes before
# the bottom row clips off-canvas.
_HAND_INSET = 54

# The seat halves are split higher than centre so the human's band gets the larger share; the
# opponent's compresses to the top edge.
_DIVIDER_FRAC = 0.42
# Each seat has three card rows stepping in from its edge, toward the divider: provinces (nearest the
# edge/hand), then stronghold + holdings, then personalities out front. Rows step by a card height
# plus a gap, and cards within a row step by a card width plus a gap, so neither touches edge-to-edge.
_ROW_GAP = 16
_CARD_GAP = 8
_ROW_STEP = CARD_H + _ROW_GAP
_COLUMN_STEP = CARD_W + _CARD_GAP


def _row_y(canvas_h: int, seat_at_bottom: bool) -> int:
    """The outermost card row, against the seat's edge; the human's sits just above the hand."""
    return canvas_h - _PROVINCE_INSET_BOTTOM if seat_at_bottom else _PROVINCE_INSET_TOP


def _holding_row_y(canvas_h: int, seat_at_bottom: bool) -> int:
    """The stronghold/holdings row: one step inward from the provinces row, toward the divider."""
    province = _row_y(canvas_h, seat_at_bottom)
    return province - _ROW_STEP if seat_at_bottom else province + _ROW_STEP


def _personality_row_y(canvas_h: int, seat_at_bottom: bool) -> int:
    """The personalities row: two steps inward from the provinces row, out in front of the
    holdings and nearest the divider."""
    province = _row_y(canvas_h, seat_at_bottom)
    return province - 2 * _ROW_STEP if seat_at_bottom else province + 2 * _ROW_STEP


def divider_y(canvas_h: int) -> int:
    """The y of the faint midline splitting the two seats' halves."""
    return int(canvas_h * _DIVIDER_FRAC)


def _hand_y(canvas_h: int, seat_at_bottom: bool) -> int:
    return canvas_h - _HAND_INSET if seat_at_bottom else _HAND_INSET


def hand_box(canvas_w: int, canvas_h: int, *, seat_at_bottom: bool) -> tuple[int, int, int, int]:
    """Screen box for a seat's hand strip, spanning most of the canvas width."""
    return canvas_w // 2, _hand_y(canvas_h, seat_at_bottom), canvas_w - 200, 108


def province_positions(
    canvas_w: int, canvas_h: int, count: int, *, seat_at_bottom: bool
) -> list[tuple[int, int]]:
    """Centre points for ``count`` provinces, centre-justified across the canvas on the seat's row.

    The columns are evenly spaced by one column step and reversed for the top seat so its leftmost
    province faces the same edge as the bottom seat's.
    """
    if count <= 0:
        return []
    y = _row_y(canvas_h, seat_at_bottom)
    center_x = canvas_w // 2
    offsets = [(i - (count - 1) / 2) * _COLUMN_STEP for i in range(count)]
    if not seat_at_bottom:
        offsets.reverse()
    return [(int(center_x + off), y) for off in offsets]


# Where a seat's home row of unplaced cards (its stronghold, sensei, and freshly recruited holdings)
# begins. The stronghold sits first, so everything that joins it later lands beside it, one column
# step to the right.
_HOME_X0 = CARD_W


def home_slot(canvas_w: int, canvas_h: int, index: int, *, seat_at_bottom: bool) -> tuple[int, int]:
    """Position for the ``index``-th unplaced card in a seat's home (holdings) row, laid left to
    right from inside the seat's edge. The stronghold, sensei, and freshly recruited holdings park
    here in battlefield order until a drag gives them a board spot."""
    return _HOME_X0 + index * _COLUMN_STEP, _holding_row_y(canvas_h, seat_at_bottom)


def home_stack_positions(
    unplaced: list[tuple[str, object]],
    canvas_w: int,
    canvas_h: int,
    *,
    seat_at_bottom: bool,
    offset: int,
    personality_row: bool = False,
) -> dict[str, tuple[int, int]]:
    """Home-row positions for a seat's unplaced cards. ``unplaced`` is a list of ``(card_id,
    group_key)`` in placement order: distinct group keys take consecutive columns, and copies
    sharing a key stack down a single column by ``offset`` each. Returns a map of card id to
    ``(x, y)``.

    With ``personality_row`` set, the cards land in the personalities row, centre-justified across
    the canvas (like the provinces); otherwise they land in the holdings row, laid out left to right
    from the seat's edge behind the stronghold.
    """
    columns: dict[object, int] = {}
    for _, key in unplaced:
        columns.setdefault(key, len(columns))

    if personality_row:  # centre-justified across the canvas, like the provinces
        center_x = canvas_w // 2
        row_y = _personality_row_y(canvas_h, seat_at_bottom)
        base = {
            col: (int(center_x + (col - (len(columns) - 1) / 2) * _COLUMN_STEP), row_y)
            for col in columns.values()
        }
    else:  # left-justified in the holdings row, behind the stronghold
        base = {
            col: home_slot(canvas_w, canvas_h, col, seat_at_bottom=seat_at_bottom)
            for col in columns.values()
        }

    copies: dict[object, int] = {}
    placed: dict[str, tuple[int, int]] = {}
    for card_id, key in unplaced:
        copy = copies.get(key, 0)
        copies[key] = copy + 1
        x, y = base[columns[key]]
        placed[card_id] = (x, y + copy * offset)
    return placed


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


def card_view_placement(
    card_cx: int,
    card_cy: int,
    card_w: int,
    card_h: int,
    view_w: int,
    view_h: int,
    canvas_w: int,
    canvas_h: int,
    gap: int = 10,
) -> tuple[int, int]:
    """The top-left canvas pixel for a card-view preview beside a card centred at
    ``(card_cx, card_cy)``: to the card's right, flipped to its left when that would overflow the
    canvas, vertically centred on the card, and clamped to sit fully on-canvas."""
    left = card_cx + card_w // 2 + gap
    if left + view_w > canvas_w:
        left = card_cx - card_w // 2 - gap - view_w
    top = card_cy - view_h // 2
    left = max(0, min(left, canvas_w - view_w))
    top = max(0, min(top, canvas_h - view_h))
    return left, top

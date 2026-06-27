from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import BoardPos, DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_gui.constants import CARD_H, CARD_W

# How far a seat's row of zones sits from the top or bottom edge, and how far the hand sits beyond
# that. The human seat occupies the bottom band; the opponent mirrors it across the top.
_ROW_INSET = 200
_HAND_INSET = 60
_DECK_INSET = 200
_DISCARD_GAP = 120


def _row_y(canvas_h: int, seat_at_bottom: bool) -> int:
    return canvas_h - _ROW_INSET if seat_at_bottom else _ROW_INSET


def _hand_y(canvas_h: int, seat_at_bottom: bool) -> int:
    return canvas_h - _HAND_INSET if seat_at_bottom else _HAND_INSET


def deck_pos(
    canvas_w: int, canvas_h: int, key: DeckKey, *, seat_at_bottom: bool
) -> tuple[int, int]:
    """Screen centre for a seat's deck. Dynasty sits left and fate right for the bottom seat; the
    top seat mirrors both across the canvas so each seat reads its own board the same way."""
    y = _row_y(canvas_h, seat_at_bottom)
    left_x, right_x = _DECK_INSET, canvas_w - _DECK_INSET
    if seat_at_bottom:
        dynasty_x, fate_x = left_x, right_x
    else:
        dynasty_x, fate_x = right_x, left_x
    return (dynasty_x, y) if key.side is Side.DYNASTY else (fate_x, y)


def discard_pos(
    canvas_w: int, canvas_h: int, key: ZoneKey, *, seat_at_bottom: bool
) -> tuple[int, int, int, int]:
    """Screen box (centre x, centre y, w, h) for a discard or banish pile, beside its deck."""
    y = _row_y(canvas_h, seat_at_bottom)
    side = (
        Side.DYNASTY
        if key.role in (ZoneRole.DYNASTY_DISCARD, ZoneRole.DYNASTY_BANISH)
        else Side.FATE
    )
    dx, _ = deck_pos(canvas_w, canvas_h, DeckKey(key.owner, side), seat_at_bottom=seat_at_bottom)
    toward_center = 1 if dx < canvas_w // 2 else -1
    gap = _DISCARD_GAP
    if key.role in (ZoneRole.FATE_BANISH, ZoneRole.DYNASTY_BANISH):
        gap *= 2  # banish stacks one slot further in than its discard
    x = max(60, min(canvas_w - 60, dx + toward_center * gap))
    return x, y, CARD_W, CARD_H


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
    """Where a battlefield card with no real position (the unplaced sentinel) is parked: just inside
    its owner's deck, fate to the deck's left and dynasty to its right, matching a fresh draw."""
    from yasuki_gui.constants import DRAW_OFFSET

    deck_owner = owner if owner is not None else PlayerId.P1
    dx, dy = deck_pos(canvas_w, canvas_h, DeckKey(deck_owner, side), seat_at_bottom=seat_at_bottom)
    offset = CARD_W + DRAW_OFFSET
    return (dx - offset if side is Side.FATE else dx + offset), dy


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

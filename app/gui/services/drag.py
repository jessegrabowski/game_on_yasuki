from dataclasses import dataclass
from enum import Enum, auto
from collections.abc import Iterable

from app.game_pieces.cards import L5RCard


class DragKind(Enum):
    NONE = auto()
    CARD = auto()
    HAND = auto()
    DECK_ARMED = auto()
    ZONE_ARMED = auto()


BBox = tuple[int, int, int, int]


@dataclass
class Drag:
    kind: DragKind = DragKind.NONE
    src_tag: str | None = None
    sprite_tag: str | None = None
    card: L5RCard | None = None
    offset: tuple[int, int] = (0, 0)
    src_bbox: BBox | None = None
    hand_origin_index: int | None = None

    @staticmethod
    def contains(bbox: BBox, x: int, y: int) -> bool:
        x0, y0, x1, y1 = bbox
        return x0 <= x <= x1 and y0 <= y <= y1

    def left_source(self, x: int, y: int) -> bool:
        return self.src_bbox is not None and not self.contains(self.src_bbox, x, y)

    def resolve_drop_target_center_first(
        self,
        x: int,
        y: int,
        zone_items: Iterable[tuple[str, BBox]],
        deck_items: Iterable[tuple[str, BBox]],
    ) -> str | None:
        """Pure resolver: given current center and the current bboxes, pick a target."""
        for ztag, zb in zone_items:
            if self.contains(zb, x, y):
                return ztag
        for dtag, db in deck_items:
            if self.contains(db, x, y):
                return dtag
        return None

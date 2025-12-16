from dataclasses import dataclass
from pathlib import Path
from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import AttachmentType, Element, Timing
from app.paths import (
    FATE_BACK,
    DEFAULT_STRATEGY,
    DEFAULT_ITEM,
    DEFAULT_RING,
)


@dataclass(frozen=True, slots=True)
class FateCard(L5RCard):
    focus: int | None = None
    gold_cost: int | None = None
    image_back: Path | None = FATE_BACK


@dataclass(frozen=True, slots=True)
class FateAction(FateCard):
    timings: tuple[Timing, ...] = ()
    image_front: Path | None = DEFAULT_STRATEGY

    def __post_init__(self):
        L5RCard.__post_init__(self)
        if not isinstance(self.timings, tuple):
            object.__setattr__(self, "timings", tuple(self.timings))


@dataclass(frozen=True, slots=True)
class FateAttachment(FateCard):
    attachment_type: AttachmentType = AttachmentType.ITEM
    attach_restrictions: tuple[str, ...] = ()
    image_front: Path | None = DEFAULT_ITEM

    def __post_init__(self):
        L5RCard.__post_init__(self)
        if not isinstance(self.attach_restrictions, tuple):
            object.__setattr__(self, "attach_restrictions", tuple(self.attach_restrictions))


@dataclass(frozen=True, slots=True)
class FateRing(FateCard):
    element: Element = Element.VOID
    image_front: Path | None = DEFAULT_RING

from abc import ABC, abstractmethod
import tkinter as tk

from yasuki_gui import theme
from yasuki_gui.constants import COUNTER_BADGE_R
from yasuki_gui.visuals.cardface import RenderCard
from yasuki_core.game_pieces.counters import SINCERITY, WEALTH

# Per-counter badge colors — (fill, count-text) — so a card carrying more than one kind reads at
# a glance. Light text on the dark gold, dark text on the light powder blue.
_COUNTER_STYLE = {
    WEALTH.key: (theme.GOLD, theme.ON_DARK),
    SINCERITY.key: (theme.POWDER_BLUE, theme.INK),
}
_DEFAULT_COUNTER_STYLE = (theme.GOLD, theme.ON_DARK)


def draw_counter_badges(
    canvas: tk.Canvas, card: RenderCard, bbox: tuple[int, int, int, int], tags: tuple[str, ...]
) -> None:
    """Draw a badge per counter kind in the card's bottom-right corner, coloured by kind with the
    count inside, stacking upward in a fixed order.

    Bottom rather than top: a card prints its Chi in the top-right, and the live stat is stamped
    over it.

    Parameters
    ----------
    canvas : tkinter.Canvas
        The canvas drawn onto.
    card : L5RCard or HiddenFace
        The card whose counters are shown. A redacted back carries none and draws nothing.
    bbox : tuple of int
        The card's rectangle as ``(x0, y0, x1, y1)``; the badges hang off its bottom-right.
    tags : tuple of str
        The canvas tags every badge item is created under, so the caller can erase them as a group.
    """
    counters = getattr(card, "counters", None)
    if not counters:
        return
    _, _, right, bottom = bbox
    cx = right - COUNTER_BADGE_R - 2
    cy = bottom - COUNTER_BADGE_R - 2
    # Iterate the counters actually on the card (sorted for a stable stack), not the whole registry
    # — so the badge system doesn't scale with the catalogue's size.
    for key, count in sorted(counters.items()):
        if count <= 0:
            continue
        fill, text_fill = _COUNTER_STYLE.get(key, _DEFAULT_COUNTER_STYLE)
        canvas.create_oval(
            cx - COUNTER_BADGE_R,
            cy - COUNTER_BADGE_R,
            cx + COUNTER_BADGE_R,
            cy + COUNTER_BADGE_R,
            fill=fill,
            outline=theme.CARD_BORDER,
            width=1,
            tags=tags,
        )
        canvas.create_text(
            cx, cy, text=str(count), fill=text_fill, font=theme.serif(9, "bold"), tags=tags
        )
        cy -= 2 * COUNTER_BADGE_R + 2


def draw_count_pill(canvas: tk.Canvas, x1: int, y1: int, count: int, tag: str) -> None:
    """A small dark count pill in a pile or deck's bottom-right corner."""
    canvas.create_rectangle(
        x1 - 22, y1 - 16, x1 - 3, y1 - 3, fill=theme.COUNT_BG, outline="", tags=(tag, "zone")
    )
    canvas.create_text(
        x1 - 12,
        y1 - 9,
        text=str(count),
        fill=theme.COUNT_FG,
        font=theme.serif(8),
        tags=(tag, "zone"),
    )


class Visual(ABC):
    @property
    @abstractmethod
    def size(self) -> tuple[int, int]: ...

    @property
    @abstractmethod
    def bbox(self) -> tuple[int, int, int, int]: ...

    @abstractmethod
    def draw(self, canvas) -> None: ...

    def intersects(self, other: "Visual") -> bool:
        ax0, ay0, ax1, ay1 = self.bbox
        bx0, by0, bx1, by1 = other.bbox
        return not (ax1 < bx0 or ax0 > bx1 or ay1 < by0 or ay0 > by1)

    def update_selection(self, canvas: tk.Canvas, selected: bool) -> None:
        canvas.delete(getattr(self, "tag", ""))
        self.draw(canvas)

    def move_to(self, canvas: tk.Canvas, x: int, y: int) -> None:
        canvas.delete(getattr(self, "tag", ""))

        setattr(self, "x", x)
        setattr(self, "y", y)

        self.draw(canvas)


class MarqueeBoxVisual(Visual):
    def __init__(self, rect: tuple[int, int, int, int]):
        self._rect = rect

    @property
    def size(self) -> tuple[int, int]:
        x0, y0, x1, y1 = self._rect
        return (max(0, x1 - x0), max(0, y1 - y0))

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return self._rect

    def draw(self, canvas) -> None:
        # Not used; required by interface
        pass

from abc import ABC, abstractmethod
import tkinter as tk

from yasuki_gui import theme


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

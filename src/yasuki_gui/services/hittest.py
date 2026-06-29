import tkinter as tk

from yasuki_gui.services.drag import BBox


def bounds_contains(bbox: BBox, x: int, y: int) -> bool:
    """Return True if point (x,y) lies within bbox (x0,y0,x1,y1)."""
    x0, y0, x1, y1 = bbox
    return x0 <= x <= x1 and y0 <= y <= y1


def resolve_drop_target(view, x: int, y: int) -> str | None:
    """Resolve a drop target tag (a hand or province zone) given a view and point. Decks and the
    other piles live off-board, so they are not drop targets."""
    for tag, hv in {**view.hands, **view.zones}.items():
        if bounds_contains(hv.bbox, x, y):
            return tag
    return None


def resolve_tag_at(view, event: tk.Event) -> str | None:
    """Return tag at event using view.find_withtag/gettags.

    The view is expected to be a tk.Canvas-like object with find_withtag and gettags.
    """
    item = view.find_withtag("current")
    if not item:
        return None
    tags = view.gettags(item[0])
    for t in tags:
        if t.startswith("card:") or t.startswith("zone:"):
            return t
    return None

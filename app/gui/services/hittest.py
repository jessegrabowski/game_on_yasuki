import tkinter as tk

from app.game_pieces.constants import Side
from app.gui.visuals import DeckVisual, CardSpriteVisual
from app.gui.services.drag import BBox


def bounds_contains(bbox: BBox, x: int, y: int) -> bool:
    """Return True if point (x,y) lies within bbox (x0,y0,x1,y1)."""
    x0, y0, x1, y1 = bbox
    return x0 <= x <= x1 and y0 <= y <= y1


def resolve_drop_target(view, x: int, y: int) -> str | None:
    """Resolve a drop target tag given a view and point.

    Preference order: hands, zones, decks.
    """
    # hands and zones first
    for tag, hv in {**view.hands, **view.zones}.items():
        if bounds_contains(hv.bbox, x, y):
            return tag
    # then decks
    for tag, dv in view.decks.items():
        if bounds_contains(dv.bbox, x, y):
            return tag
    return None


def deck_expected_side(dv: DeckVisual) -> Side | None:
    """Return expected Side for a deck visual"""
    if "Fate" in getattr(dv, "label", ""):
        return Side.FATE
    if "Dynasty" in getattr(dv, "label", ""):
        return Side.DYNASTY
    top = dv.deck.peek(1)
    return top[0].side if top else None


def deck_hit_for_sprite(view, sprite: CardSpriteVisual) -> str | None:
    """Return deck tag under the sprite center or intersecting, if any."""
    cx, cy = sprite.x, sprite.y
    for tag, dv in view.decks.items():
        x0, y0, x1, y1 = dv.bbox
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            return tag
    for tag, dv in view.decks.items():
        if sprite.intersects(dv):
            return tag
    return None


def zone_hit_for_sprite(view, sprite: CardSpriteVisual) -> str | None:
    cx, cy = sprite.x, sprite.y
    for tag, zv in view.zones.items():
        x0, y0, x1, y1 = zv.bbox
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            return tag
    for tag, zv in view.zones.items():
        if sprite.intersects(zv):
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
        if t.startswith("card:") or t.startswith("deck:") or t.startswith("zone:"):
            return t
    return None

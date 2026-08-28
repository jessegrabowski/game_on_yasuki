import tkinter as tk
from typing import NamedTuple

from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.game_pieces.constants import AttachmentType
from yasuki_core.game_pieces.prints import AttachmentPrint, PersonalityPrint

from yasuki_gui import theme
from yasuki_gui.constants import (
    CHI_ANCHOR,
    FORCE_ANCHOR,
    STAT_BOX_H,
    STAT_BOX_W,
    STAT_DIGIT_W,
    STAT_FONT_PX,
)
from yasuki_gui.visuals.cardface import RenderCard

# A bowed card is drawn turned a quarter clockwise, so its stamps turn with it: the text is set at
# 270° counter-clockwise, which is the same quarter the other way.
_BOWED_TEXT_ANGLE = 270
# The tab's outline is drawn centred on its edge, so it reaches this far past it. Counted in the
# clamp, or a stamp pushed against the card's edge hangs a hairline over whatever is behind it.
_OUTLINE = 1

# Where each stat is stamped, and the colour of the printed banner it covers.
_SLOTS = {
    Stat.FORCE: (FORCE_ANCHOR, theme.FORCE_BANNER),
    Stat.CHI: (CHI_ANCHOR, theme.CHI_BANNER),
}


class StatReading(NamedTuple):
    """A stat as it stands, against the number the card prints.

    Attributes
    ----------
    value : int
        The effective stat, modifiers included.
    printed : int
        What the card prints, which is what ``value`` is coloured against.
    """

    value: int
    printed: int


def stamped_stats(card: RenderCard, stats: dict[str, dict[Stat, int]]) -> dict[Stat, StatReading]:
    """The stats to stamp on ``card``, keyed by stat and empty for a card that carries none.

    A Personality answers with Force and Chi. A Follower stands in the unit and so carries a Force
    of its own but no Chi, and every other card carries neither — an Item's contribution is a
    modifier, already folded into the Personality's Force by the time it is read here.

    Parameters
    ----------
    card : L5RCard or HiddenFace
        The card being drawn. A redacted back carries no print and so no stat.
    stats : dict mapping str to dict
        :attr:`GameView.stats` — each modified card's effective stats by id. A card no modifier
        reaches is absent, and its printed value stands.
    """
    printed = getattr(card, "printed", None)
    if isinstance(printed, PersonalityPrint):
        bases = {Stat.FORCE: printed.force, Stat.CHI: printed.chi}
    elif (
        isinstance(printed, AttachmentPrint) and printed.attachment_type is AttachmentType.FOLLOWER
    ):
        bases = {Stat.FORCE: printed.force}
    else:
        return {}
    modified = stats.get(card.id, {})
    return {stat: StatReading(modified.get(stat, base), base) for stat, base in bases.items()}


def _colour(reading: StatReading) -> str:
    if reading.value > reading.printed:
        return theme.STAT_UP
    if reading.value < reading.printed:
        return theme.STAT_DOWN
    return theme.STAT_PRINTED


def _anchor(
    fraction: tuple[float, float], bbox: tuple[int, int, int, int], bowed: bool
) -> tuple[float, float]:
    """Where a printed stat sits on a card drawn at ``bbox``.

    The fractions measure an upright card. Bowing turns the card a quarter clockwise, which carries
    a point at ``(fx, fy)`` to ``(1 - fy, fx)`` — both stats end up down the card's right edge,
    over the printing they cover.
    """
    x0, y0, x1, y1 = bbox
    fx, fy = (1 - fraction[1], fraction[0]) if bowed else fraction
    return x0 + fx * (x1 - x0), y0 + fy * (y1 - y0)


def draw_stat_stamps(
    canvas: tk.Canvas,
    card: RenderCard,
    bbox: tuple[int, int, int, int],
    stats: dict[str, dict[Stat, int]] | None,
    tags: tuple[str, ...],
    *,
    bowed: bool = False,
) -> None:
    """Stamp ``card``'s live Force and Chi over the numerals it prints them in.

    Every card that has the stat is stamped, not only a modified one.

    Parameters
    ----------
    canvas : tkinter.Canvas
        The canvas drawn onto.
    card : L5RCard or HiddenFace
        The card being stamped.
    bbox : tuple of int
        The card's rectangle as ``(x0, y0, x1, y1)``, already turned if the card is bowed.
    stats : dict mapping str to dict
        :attr:`GameView.stats`, read through :func:`stamped_stats`.
    tags : tuple of str
        The canvas tags every item is created under, so the caller can erase them as a group.
    bowed : bool, optional
        Whether the card is drawn on its side, which turns each stamp with it. Default False.
    """
    if stats is None or not getattr(card, "face_up", False):
        return
    x0, y0, x1, y1 = bbox
    font = theme.numerals(STAT_FONT_PX)
    for stat, reading in stamped_stats(card, stats).items():
        fraction, banner = _SLOTS[stat]
        text = str(reading.value)
        width = STAT_BOX_W + STAT_DIGIT_W * (len(text) - 1)
        half_w, half_h = width / 2, STAT_BOX_H / 2
        if bowed:
            half_w, half_h = half_h, half_w
        cx, cy = _anchor(fraction, bbox, bowed)
        # A wide number is nudged back onto the card rather than clipped by its edge.
        cx = min(max(cx, x0 + half_w + _OUTLINE), x1 - half_w - _OUTLINE)
        cy = min(max(cy, y0 + half_h + _OUTLINE), y1 - half_h - _OUTLINE)
        canvas.create_rectangle(
            cx - half_w,
            cy - half_h,
            cx + half_w,
            cy + half_h,
            fill=banner,
            outline=theme.INK,
            width=_OUTLINE,
            tags=tags,
        )
        canvas.create_text(
            cx,
            cy,
            text=text,
            fill=_colour(reading),
            font=font,
            angle=_BOWED_TEXT_ANGLE if bowed else 0,
            tags=tags,
        )

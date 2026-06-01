from collections.abc import Iterable

from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

# Actual card size and sheet layout, measured from the reference print sheet: cards print at
# 63.5 x 90 mm, 4 columns x 2 rows on landscape US Letter, with a 3 mm gutter between cards to cut
# along for proxies. This spec is the single source of truth for both the desktop and web exports.
CARD_W = 63.5 * mm
CARD_H = 90.0 * mm
GUTTER = 3.0 * mm
COLS = 4
ROWS = 2
PER_PAGE = COLS * ROWS
PAGE_W, PAGE_H = landscape(letter)

_GRID_W = COLS * CARD_W + (COLS - 1) * GUTTER
_GRID_H = ROWS * CARD_H + (ROWS - 1) * GUTTER
_MARGIN_X = (PAGE_W - _GRID_W) / 2
_MARGIN_Y = (PAGE_H - _GRID_H) / 2


def slot_position(index: int) -> tuple[int, float, float]:
    """Page number and bottom-left (x, y) in points for the card at sheet position ``index``.

    The grid is centered on the page and filled left-to-right, top-to-bottom."""
    page, slot = divmod(index, PER_PAGE)
    col, row = slot % COLS, slot // COLS
    x = _MARGIN_X + col * (CARD_W + GUTTER)
    y = PAGE_H - _MARGIN_Y - row * (CARD_H + GUTTER) - CARD_H
    return page, x, y


def render_deck_pdf(images: Iterable, out_path) -> int:
    """Lay card images out at actual card size, ``PER_PAGE`` to a page, and write the PDF.

    Parameters
    ----------
    images : iterable of path or PIL image
        One entry per card to print (already expanded by copy count), in print order. Anything
        ``reportlab.lib.utils.ImageReader`` accepts.
    out_path : path
        Destination PDF path.

    Returns
    -------
    pages : int
        Number of pages written.
    """
    pdf = canvas.Canvas(str(out_path), pagesize=(PAGE_W, PAGE_H))
    pages = 0
    for index, image in enumerate(images):
        page, x, y = slot_position(index)
        if page > pages:
            pdf.showPage()
            pages = page
        pdf.drawImage(ImageReader(image), x, y, CARD_W, CARD_H)
    pdf.showPage()
    pdf.save()
    return pages + 1

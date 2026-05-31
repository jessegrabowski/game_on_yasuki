from PIL import Image
from reportlab.lib.units import mm

from yasuki_core.deck_pdf import (
    CARD_H,
    CARD_W,
    COLS,
    PAGE_H,
    PAGE_W,
    PER_PAGE,
    ROWS,
    render_deck_pdf,
    slot_position,
)


def test_spec_matches_measured_card_size_and_fits_the_page():
    assert PER_PAGE == COLS * ROWS == 8
    assert (CARD_W, CARD_H) == (63.5 * mm, 90.0 * mm)
    assert COLS * CARD_W <= PAGE_W
    assert ROWS * CARD_H <= PAGE_H


def test_slot_position_advances_grid_and_paginates():
    p0, x0, y0 = slot_position(0)
    p1, x1, y1 = slot_position(1)  # next column, same row
    p4, x4, y4 = slot_position(4)  # next row, first column
    p8, _, y8 = slot_position(8)  # next page

    assert (p0, p4, p8) == (0, 0, 1)
    assert x1 > x0 and y1 == y0  # columns advance rightward
    assert x4 == x0 and y4 < y0  # rows advance downward (lower y on the page)
    assert y8 == y0  # a fresh page restarts at the top row


def test_render_deck_pdf_paginates_and_writes_pdf(tmp_path):
    images = [Image.new("RGB", (744, 1051), "red") for _ in range(9)]
    out = tmp_path / "deck.pdf"
    pages = render_deck_pdf(images, out)
    assert pages == 2  # 9 cards -> two 8-up pages
    assert out.read_bytes()[:4] == b"%PDF"

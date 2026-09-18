import tkinter as tk

import pytest

from yasuki_gui import theme
from yasuki_gui.constants import CARD_H, CARD_W
from yasuki_gui.ui.card_strip import CELL_PAD, STRIP_H, STRIP_W, CardStrip
from yasuki_gui.ui.floating_panel import BORDER, TITLEBAR_H

from tests.yasuki_core.engine.builders import personality
from tests.yasuki_gui.conftest import DummyEventNamespace, PreviewOnlyImages


def _card(card_id: str = "a-card", *, face_up: bool = True, bowed: bool = False):
    card = personality(card_id, name=card_id.title())
    if not face_up:
        card.turn_face_down()
    if bowed:
        card.bow()
    return card


@pytest.fixture
def board():
    root = tk.Tk()
    root.geometry("900x700+0+0")
    frame = tk.Frame(root, width=900, height=700)
    frame.pack(fill="both", expand=True)
    root.update()
    try:
        yield frame
    finally:
        root.destroy()


def _center_x(strip, tag) -> int:
    return strip._drawn[tag].x


def _texts(canvas) -> list[str]:
    return [
        canvas.itemcget(item, "text") for item in canvas.find_all() if canvas.type(item) == "text"
    ]


def test_showing_a_pile_titles_the_strip_after_it(board):
    """One panel serves every pile, so what it is showing has to be readable off its title bar."""
    strip = CardStrip(board, PreviewOnlyImages())

    strip.show([_card()], "Fate Discard")
    assert strip._title.cget("text") == "Fate Discard"

    strip.show([], "Dynasty Banish")
    assert strip._title.cget("text") == "Dynasty Banish"


def test_showing_a_pile_replaces_the_one_before_it(board):
    """Reopening on another pile must not leave the previous pile's cards behind it."""
    strip = CardStrip(board, PreviewOnlyImages())
    strip.show([_card("one"), _card("two")], "Fate Discard")

    strip.show([_card("three")], "Dynasty Discard")

    assert _texts(strip.canvas) == ["Three"]


def test_cards_run_left_to_right_a_pad_apart(board):
    strip = CardStrip(board, PreviewOnlyImages())

    strip.show([_card("one"), _card("two")], "Fate Discard")

    assert _center_x(strip, "card:one") == CELL_PAD + CARD_W // 2
    assert _center_x(strip, "card:two") == 2 * CELL_PAD + CARD_W + CARD_W // 2


def test_a_bowed_card_takes_its_turned_width(board):
    strip = CardStrip(board, PreviewOnlyImages())

    strip.show([_card("one", bowed=True), _card("two")], "Fate Discard")

    assert _center_x(strip, "card:one") == CELL_PAD + CARD_H // 2
    assert _center_x(strip, "card:two") == 2 * CELL_PAD + CARD_H + CARD_W // 2


def test_the_strip_scrolls_over_exactly_the_row(board):
    strip = CardStrip(board, PreviewOnlyImages())

    strip.show([_card("one"), _card("two")], "Fate Discard")

    right = 3 * CELL_PAD + 2 * CARD_W
    assert strip.canvas.cget("scrollregion") == f"0 0 {right} {2 * CELL_PAD + CARD_H}"


def test_a_strip_of_backs_names_only_the_face_up_card(board):
    """The property the opponent-hand view rests on: one revealed card among concealed ones is the
    only one a reader can identify."""
    strip = CardStrip(board, PreviewOnlyImages())

    strip.show(
        [_card("a", face_up=False), _card("favor", face_up=True), _card("b", face_up=False)],
        "Hand",
    )

    assert _texts(strip.canvas) == ["Favor"]


def test_a_pile_with_no_art_names_its_face_up_cards_and_draws_backs(board):
    """Art is fetched over the network and cached, so a strip opened before it arrives has to read
    as the pile it is rather than as a row of blank cells."""
    strip = CardStrip(board, PreviewOnlyImages())

    strip.show([_card("hida-kisada"), _card("hidden", face_up=False)], "Fate Discard")

    assert _texts(strip.canvas) == ["Hida-Kisada"]
    backs = [
        item
        for item in strip.canvas.find_all()
        if strip.canvas.type(item) == "rectangle"
        and strip.canvas.itemcget(item, "fill") == theme.CARD_BACK
    ]
    assert len(backs) == 1


def test_a_scrolled_strip_finds_the_card_under_the_pointer(board):
    """A click lands in window coordinates and the cards sit in canvas coordinates, which part ways
    the moment the strip scrolls."""
    strip = CardStrip(board, PreviewOnlyImages())
    strip.open_at(10, 10)
    strip.show([_card(f"card-{index}") for index in range(20)], "Fate Deck")
    strip.canvas.xview_moveto(1.0)
    strip.update_idletasks()
    scrolled_by = strip.canvas.canvasx(0)
    assert scrolled_by > 0

    at_window_x = _center_x(strip, "card:card-19") - scrolled_by
    assert strip.card_at(DummyEventNamespace(x=at_window_x, y=CELL_PAD + CARD_H // 2)) == "card-19"


def test_the_scrollbar_is_laid_out_under_the_cards(board):
    """The canvas already fills the body when the strip adds its scrollbar, and pack hands out room
    in packing order, so a scrollbar packed after it is mapped nowhere and the pile past the panel's
    edge is unreachable."""
    strip = CardStrip(board, PreviewOnlyImages())
    strip.open_at(10, 10)
    strip.show([_card(f"card-{index}") for index in range(20)], "Fate Deck")
    strip.update_idletasks()

    assert strip.body.pack_slaves()[0] is strip._scroll


def test_the_strip_opens_exactly_one_row_tall(board):
    """The strip never wraps, and its height is what tells the player so."""
    strip = CardStrip(board, PreviewOnlyImages())
    strip.open_over(10, 10, STRIP_W, STRIP_H)
    strip.show([_card("one")], "Fate Discard")
    strip.update_idletasks()

    assert strip.place_info()["height"] == str(STRIP_H)
    row_and_bar = 2 * CELL_PAD + CARD_H + strip._scroll.winfo_reqheight()
    assert STRIP_H - TITLEBAR_H - 2 * BORDER == row_and_bar


def test_the_wheel_scrolls_the_row(board):
    strip = CardStrip(board, PreviewOnlyImages())
    strip.open_at(10, 10)
    strip.show([_card(f"card-{index}") for index in range(20)], "Fate Deck")
    strip.update_idletasks()

    strip._on_wheel(DummyEventNamespace(delta=-1))

    assert strip.canvas.canvasx(0) == CARD_W + CELL_PAD

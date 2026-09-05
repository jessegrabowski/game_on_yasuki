import tkinter as tk
from unittest.mock import Mock

import pytest

from yasuki_core.game_pieces.constants import Side
from yasuki_gui.ui.card_preview import CardPreview
from yasuki_gui.ui.card_strip import CardStrip, card_face


class _Images:
    """Records which face was asked for, so a test reads the decision rather than the pixels.

    A sized request is the preview's and an unsized one a cell's, so the two are answered
    separately: cells with no art fall through to named placeholders, while the preview needs a real
    Tk image, which is the only thing Tk will build a label from.
    """

    def __init__(self, front=None, back=None, preview=None):
        self._front, self._back, self._preview = front, back, preview
        self.asked: list[str] = []

    def front(self, image_front, bowed, inverted, target=None):
        self.asked.append("front")
        return self._preview if target else self._front

    def back(self, side, bowed, inverted, image_back, target=None):
        self.asked.append("back")
        return self._preview if target else self._back


def _card(*, face_up: bool, name: str = "A Card"):
    card = Mock()
    card.name = name
    card.face_up = face_up
    card.bowed = False
    card.inverted = False
    card.side = Side.FATE
    card.image_front = None
    card.image_back = None
    return card


@pytest.mark.parametrize("face_up, expected", [(True, "front"), (False, "back")])
def test_a_card_shows_the_face_it_is_turned_to(face_up, expected):
    images = _Images(front="front-art", back="back-art")

    photo = card_face(images, _card(face_up=face_up))

    assert images.asked == [expected]
    assert photo == f"{expected}-art"


def test_a_strip_of_backs_shows_only_the_face_up_card():
    """The property the opponent-hand view rests on: one revealed card among concealed ones is the
    only one a reader can identify."""
    images = _Images(front="front-art", back="back-art")
    hand = [
        _card(face_up=False),
        _card(face_up=True, name="The Imperial Favor"),
        _card(face_up=False),
    ]

    faces = [card_face(images, card) for card in hand]

    assert faces == ["back-art", "front-art", "back-art"]


def test_a_missing_image_falls_through_to_the_caller():
    """A card with no art returns None so the strip can draw its name instead of an empty cell."""
    assert card_face(_Images(), _card(face_up=True)) is None


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


@pytest.fixture
def art(board):
    """A real one-pixel image, for the preview label Tk refuses to build from anything else."""
    return tk.PhotoImage(master=board, width=1, height=1)


def test_showing_a_pile_titles_the_strip_after_it(board):
    """One panel serves every pile, so what it is showing has to be readable off its title bar."""
    strip = CardStrip(board, _Images())

    strip.show([_card(face_up=True)], "Fate Discard")
    assert strip._title.cget("text") == "Fate Discard"

    strip.show([], "Dynasty Banish")
    assert strip._title.cget("text") == "Dynasty Banish"


def test_showing_a_pile_replaces_the_one_before_it(board):
    """Reopening on another pile must not leave the previous pile's cards behind it."""
    strip = CardStrip(board, _Images())
    strip.show([_card(face_up=True), _card(face_up=True)], "Fate Discard")

    strip.show([_card(face_up=True)], "Dynasty Discard")

    assert len(strip._row.winfo_children()) == 1


def test_the_scrollregion_is_re_read_when_the_row_settles(board):
    """The cards are laid out after the panel is placed, so a scrollregion measured while filling
    would be the wrong size until something forced a redraw."""
    strip = CardStrip(board, _Images())
    strip.open_at(10, 10)
    strip.show([_card(face_up=True), _card(face_up=True)], "Fate Discard")

    assert strip._row.bind("<Configure>"), "the row re-reports its size as it is laid out"
    strip._fit_scrollregion()
    assert strip._canvas.cget("scrollregion")


def _strip_with_preview(board, art):
    """A strip wired the way the game window wires it: one preview drawn on the window."""
    strip = CardStrip(board, _Images(preview=art))
    strip.preview = CardPreview(board, _Images(preview=art))
    return strip


def test_the_preview_key_enlarges_the_hovered_card(board, art):
    """The board previews a card under the pointer with V; a card in the strip reads the same way."""
    strip = _strip_with_preview(board, art)
    strip.show([_card(face_up=True)], "Fate Discard")
    strip.open_at(10, 10)
    strip._set_hovered((_card(face_up=True), strip))

    strip._toggle_preview()

    assert strip.preview.showing


def test_the_preview_key_does_nothing_with_no_card_under_the_pointer(board, art):
    """Pressing it over the panel's chrome or empty space must not conjure a preview."""
    strip = _strip_with_preview(board, art)
    strip.show([], "Fate Discard")
    strip.open_at(10, 10)

    strip._toggle_preview()

    assert not strip.preview.showing


def test_the_preview_key_is_ignored_while_the_strip_is_closed(board, art):
    """The key is bound for the panel's whole life, so a closed strip has to leave the press to the
    board's own preview rather than acting on cards nobody can see."""
    strip = _strip_with_preview(board, art)
    strip._set_hovered((_card(face_up=True), strip))

    strip._toggle_preview()

    assert not strip.preview.showing


def test_a_second_press_puts_the_preview_away(board, art):
    strip = _strip_with_preview(board, art)
    strip.open_at(10, 10)
    strip._set_hovered((_card(face_up=True), strip))
    strip._toggle_preview()

    strip._toggle_preview()

    assert not strip.preview.showing


def test_closing_the_strip_drops_its_preview(board, art):
    strip = _strip_with_preview(board, art)
    strip.open_at(10, 10)
    strip._set_hovered((_card(face_up=True), strip))
    strip._toggle_preview()

    strip.close()

    assert not strip.preview.showing


def test_reopening_the_strip_does_not_stack_preview_keys(board, art):
    """The key is bound once for the panel's life. Binding it per open would stack handlers, and an
    even number of them toggles the preview straight back off, so V would silently stop working
    after the first pile."""
    strip = _strip_with_preview(board, art)
    key = f"<KeyPress-{strip.hotkeys.view}>"
    bound_once = strip.bind_all(key)

    for pile in ("Fate Discard", "Dynasty Discard", "Fate Banish"):
        strip.open_at(10, 10)
        strip.show([_card(face_up=True)], pile)

    assert strip.bind_all(key) == bound_once


def test_a_pile_with_no_art_still_names_every_card(board):
    """Art is fetched over the network and cached, so a strip opened before it arrives has to read
    as the pile it is rather than as a row of blank cells."""
    strip = CardStrip(board, _Images())

    strip.show([_card(face_up=True, name="Hida Kisada"), _card(face_up=False)], "Fate Discard")

    placeholders = [
        child
        for holder in strip._row.winfo_children()
        for child in holder.winfo_children()
        if isinstance(child, tk.Canvas)
    ]
    assert len(placeholders) == 2
    assert placeholders[0].itemcget(1, "text") == "Hida Kisada"


def test_an_open_strip_leaves_a_board_preview_alone(board, art):
    """The key is bound app-wide and the strip's handler runs after the board's, so a strip that
    took every press would close the preview the board had just opened -- with the strip open, V
    over a battlefield card would do nothing at all."""
    strip = _strip_with_preview(board, art)
    strip.open_at(10, 10)
    strip.show([_card(face_up=True)], "Fate Discard")
    strip._set_hovered(None)  # the pointer is over the board, not the strip
    strip.preview.show(_card(face_up=True), board.winfo_rootx(), board.winfo_rooty())

    strip._toggle_preview()

    assert strip.preview.showing


def test_an_open_strip_still_closes_its_own_preview(board, art):
    """The guard above must not cost the strip its own second-press close."""
    strip = _strip_with_preview(board, art)
    strip.open_at(10, 10)
    strip._set_hovered((_card(face_up=True), strip))
    strip._toggle_preview()
    assert strip.preview.showing

    strip._toggle_preview()

    assert not strip.preview.showing

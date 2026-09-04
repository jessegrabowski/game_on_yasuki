import tkinter as tk
from unittest.mock import Mock

import pytest

from yasuki_core.game_pieces.constants import Side
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

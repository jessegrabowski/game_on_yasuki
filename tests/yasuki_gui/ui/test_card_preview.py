import tkinter as tk
from unittest.mock import Mock

import pytest

from yasuki_core.game_pieces.constants import Side
from yasuki_gui.ui.card_preview import CardPreview


class _Images:
    """Answers only the sized requests a preview makes."""

    def __init__(self, art):
        self.art = art
        self.asked: list[str] = []

    def front(self, image_front, bowed, inverted, target=None):
        self.asked.append("front")
        return self.art

    def back(self, side, bowed, inverted, image_back, target=None):
        self.asked.append("back")
        return self.art


@pytest.fixture
def host():
    root = tk.Tk()
    root.geometry("900x700+0+0")
    root.update()
    try:
        yield root
    finally:
        root.destroy()


@pytest.fixture
def art(host):
    return tk.PhotoImage(master=host, width=1, height=1)


def _card(face_up: bool):
    card = Mock()
    card.face_up = face_up
    card.side = Side.FATE
    card.image_front = None
    card.image_back = None
    card.active_face.image_front = None
    return card


def test_the_preview_is_drawn_on_the_window_not_the_caller(host, art):
    """Drawn on the window, so a panel laid over the board can neither hide it nor clip it to the
    panel's own size."""
    panel = tk.Frame(host, width=200, height=120)
    panel.place(x=0, y=0)
    preview = CardPreview(host, _Images(art))

    preview.show(_card(face_up=True), host.winfo_rootx() + 50, host.winfo_rooty() + 50)

    assert preview._label.master is host


def test_a_face_down_card_previews_its_back(host, art):
    """A preview must not reveal what the board conceals."""
    images = _Images(art)
    preview = CardPreview(host, images)

    preview.show(_card(face_up=False), host.winfo_rootx(), host.winfo_rooty())

    assert images.asked == ["back"]


def test_showing_twice_leaves_one_preview(host, art):
    """Previewing another card replaces the first rather than stacking labels on the window."""
    preview = CardPreview(host, _Images(art))
    preview.show(_card(face_up=True), host.winfo_rootx(), host.winfo_rooty())
    first = preview._label

    preview.show(_card(face_up=True), host.winfo_rootx() + 100, host.winfo_rooty())

    assert preview._label is not first
    assert not first.winfo_exists()


def test_hiding_with_nothing_up_is_harmless(host, art):
    CardPreview(host, _Images(art)).hide()


def test_a_card_with_no_art_shows_no_preview(host):
    preview = CardPreview(host, _Images(None))

    preview.show(_card(face_up=True), host.winfo_rootx(), host.winfo_rooty())

    assert not preview.showing

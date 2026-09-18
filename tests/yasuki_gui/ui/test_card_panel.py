import tkinter as tk

import pytest

from yasuki_gui.ui.card_panel import CardPanel

from tests.yasuki_core.engine.builders import personality
from tests.yasuki_gui.conftest import DummyEventNamespace


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


def _panel(board, tag_prefix="card:"):
    panel = CardPanel(board, "Cards", width=600, height=300, tag_prefix=tag_prefix)
    panel.open_at(10, 10)
    board.update_idletasks()
    return panel


def _center(panel, tag):
    left, top, right, bottom = panel.canvas.bbox(tag)
    return (left + right) // 2, (top + bottom) // 2


def _event(x, y):
    return DummyEventNamespace(x=x, y=y)


def test_a_drawn_card_is_found_at_its_center(board):
    panel = _panel(board)
    tag = panel.draw_card(personality("hida"), 100, 80)

    assert tag == "card:hida"
    assert panel.card_at(_event(*_center(panel, tag))) == "hida"


def test_bare_canvas_holds_no_card(board):
    panel = _panel(board)
    panel.draw_card(personality("hida"), 100, 80)

    assert panel.card_at(_event(500, 250)) is None


def test_the_topmost_of_overlapping_cards_answers(board):
    panel = _panel(board)
    panel.draw_card(personality("behind"), 100, 80)
    panel.draw_card(personality("front"), 110, 90)

    assert panel.card_at(_event(*_center(panel, "card:front"))) == "front"


def test_an_unpickable_card_is_not_answered(board):
    """A Province card in a lane is drawn with the sprites but is nothing the player can pick."""
    panel = _panel(board)
    tag = panel.draw_card(personality("province"), 100, 80, pickable=False)

    assert tag == "card:shown:province"
    assert panel.card_at(_event(*_center(panel, tag))) is None


def test_clearing_forgets_the_cards(board):
    panel = _panel(board)
    panel.draw_card(personality("hida"), 100, 80)

    panel.clear()

    assert panel.canvas.find_all() == ()
    assert panel.card_at(_event(100, 80)) is None


def _screen(panel, tag):
    x, y = _center(panel, tag)
    return panel.canvas.winfo_rootx() + x, panel.canvas.winfo_rooty() + y


def test_the_card_under_a_screen_point_is_reported_with_its_center(board):
    panel = _panel(board)
    tag = panel.draw_card(personality("hida"), 100, 80)

    card, x_root, y_root = panel.card_under_pointer(*_screen(panel, tag))

    assert card.id == "hida"
    assert (x_root, y_root) == (panel.canvas.winfo_rootx() + 100, panel.canvas.winfo_rooty() + 80)


def test_a_card_under_another_prefix_is_still_under_the_pointer(board):
    """Not pickable is not the same as not lookable: the Province in a lane can still be read."""
    panel = _panel(board)
    tag = panel.draw_card(personality("province"), 100, 80, pickable=False)

    found = panel.card_under_pointer(*_screen(panel, tag))

    assert found is not None and found[0].id == "province"


def test_bare_canvas_is_nothing_under_the_pointer(board):
    panel = _panel(board)
    panel.draw_card(personality("hida"), 100, 80)

    assert (
        panel.card_under_pointer(panel.canvas.winfo_rootx() + 500, panel.canvas.winfo_rooty() + 250)
        is None
    )


def test_a_point_off_the_panel_is_nothing_under_the_pointer(board):
    """A point past the canvas edge could still overlap a card drawn off-screen or scrolled away,
    which the player cannot see and must not preview."""
    panel = _panel(board)
    panel.draw_card(personality("hida"), 100, 80)

    assert (
        panel.card_under_pointer(panel.canvas.winfo_rootx() - 5, panel.canvas.winfo_rooty() + 80)
        is None
    )


def test_a_closed_panel_is_nothing_under_the_pointer(board):
    panel = _panel(board)
    tag = panel.draw_card(personality("hida"), 100, 80)
    point = _screen(panel, tag)
    panel.close()

    assert panel.card_under_pointer(*point) is None


def test_a_rolled_up_panel_is_nothing_under_the_pointer(board):
    panel = _panel(board)
    tag = panel.draw_card(personality("hida"), 100, 80)
    point = _screen(panel, tag)
    panel.toggle_minimized()

    assert panel.card_under_pointer(*point) is None

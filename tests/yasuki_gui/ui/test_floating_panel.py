import tkinter as tk

import pytest

from yasuki_gui.ui.floating_panel import (
    FloatingPanel,
    KEEP_VISIBLE,
    MIN_H,
    MIN_W,
    ROLL_UP,
    ROLLED_H,
    UNROLL,
)


@pytest.fixture
def board():
    """A 800x600 widget for a panel to float over, mapped so it reports a real size to the clamp."""
    root = tk.Tk()
    root.geometry("800x600+0+0")
    frame = tk.Frame(root, width=800, height=600)
    frame.pack(fill="both", expand=True)
    root.update()
    try:
        yield frame
    finally:
        root.destroy()


class _drag:
    """The two fields the panel reads off a pointer event: where it is on the screen."""

    def __init__(self, x_root: int, y_root: int):
        self.x_root, self.y_root = x_root, y_root


def _shrink(panel: FloatingPanel, board: tk.Frame, width: int, height: int) -> None:
    """Resize the window the board fills, then hand the panel the notice Tk would.

    The suite withdraws every root so tests do not flash windows on screen, and a withdrawn window
    is never sent ``<Configure>`` — so the handler is called rather than awaited. That the handler
    is wired to the event at all is :func:`test_the_panel_listens_for_the_board_resizing`.
    """
    board.master.geometry(f"{width}x{height}")
    board.update_idletasks()
    panel._on_board_resized(None)


def _geometry(panel: FloatingPanel) -> tuple[int, int, int, int]:
    """Where the panel is placed and how big, as Tk has it rather than as the panel remembers it."""
    info = panel.place_info()
    return int(info["x"]), int(info["y"]), int(info["width"]), int(info["height"])


def test_a_panel_is_not_showing_until_it_is_opened(board):
    panel = FloatingPanel(board, "Attack", width=400, height=300)

    assert not panel.showing


def test_opening_lays_the_panel_out_at_the_size_it_was_built_with(board):
    panel = FloatingPanel(board, "Attack", width=400, height=300)

    panel.open_at(60, 40)

    assert _geometry(panel) == (60, 40, 400, 300)


def test_closing_takes_the_panel_off_the_board(board):
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(60, 40)

    panel.close()

    assert not panel.showing


def test_dragging_moves_the_panel_by_how_far_the_pointer_travelled(board):
    """By the travel rather than to the pointer, so grabbing the bar's right end does not snap the
    panel's left corner under the cursor."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(100, 100)

    panel._grab(_drag(500, 500))
    panel._drag(_drag(530, 480))

    assert _geometry(panel)[:2] == (130, 80)


def test_a_panel_cannot_be_dragged_off_the_board(board):
    """It is only grabbable by its title bar, so one pushed past the edge could never be recovered.

    Down to a strip of bar rather than the whole panel: what has to stay reachable is somewhere to
    take hold of, and demanding the whole panel fit would strand one resized larger than the board.
    """
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(100, 100)

    panel._grab(_drag(500, 500))
    panel._drag(_drag(5000, 5000))

    x, y, _, _ = _geometry(panel)
    assert (x, y) == (800 - KEEP_VISIBLE, 600 - ROLLED_H)


def test_a_panel_cannot_be_resized_larger_than_the_board(board):
    """Its resize corner rides its bottom-right, so a panel bigger than what it floats over would
    put the only handle that shrinks it past the edge."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(200, 100)

    panel._grab(_drag(500, 500))
    panel._resize(_drag(1500, 1500))

    assert _geometry(panel)[2:] == (800, 600)


def test_a_panel_at_its_full_width_still_drags(board):
    """A panel as wide as the board has a range of legal positions, not one — it slides until a
    strip of bar is all that is left on."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(200, 100)
    panel._grab(_drag(500, 500))
    panel._resize(_drag(1500, 500))

    panel._grab(_drag(500, 500))
    panel._drag(_drag(510, 500))

    assert _geometry(panel)[0] == 210


def test_a_panel_dragged_to_the_bottom_keeps_its_whole_title_bar_on_the_board(board):
    """The whole rolled-up height, border included, stays on: the bar is the only place the panel
    can be grabbed, and a bar half off the bottom is half a handle."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(100, 100)

    panel._grab(_drag(500, 500))
    panel._drag(_drag(500, 5000))

    top = _geometry(panel)[1]
    assert top + ROLLED_H == 600


def test_a_panel_cannot_be_dragged_above_or_left_of_the_board(board):
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(100, 100)

    panel._grab(_drag(500, 500))
    panel._drag(_drag(0, 0))

    assert _geometry(panel)[:2] == (0, 0)


def test_the_corner_resizes_the_panel(board):
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(50, 50)

    panel._grab(_drag(500, 500))
    panel._resize(_drag(560, 530))

    assert _geometry(panel) == (50, 50, 460, 330)


def test_a_panel_does_not_resize_below_what_still_holds_content(board):
    """A panel shrunk to nothing would keep its title bar and lose the corner that grows it back."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(50, 50)

    panel._grab(_drag(500, 500))
    panel._resize(_drag(0, 0))

    assert _geometry(panel)[2:] == (MIN_W, MIN_H)


def test_minimizing_rolls_the_panel_up_to_its_title_bar(board):
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(50, 50)

    panel.toggle_minimized()

    assert panel.minimized
    assert _geometry(panel) == (50, 50, 400, ROLLED_H)


def test_a_minimized_panel_unrolls_to_the_size_it_had(board):
    """Including a size the player resized it to, which is the one they would have to set again."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(50, 50)
    panel._grab(_drag(500, 500))
    panel._resize(_drag(560, 530))

    panel.toggle_minimized()
    panel.toggle_minimized()

    assert _geometry(panel)[2:] == (460, 330)


def test_the_button_says_which_way_it_will_roll_the_panel(board):
    """It is the only control on the bar, so a glyph that never changes leaves a rolled-up panel
    looking like it has no way back."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(50, 50)
    assert panel._roll.cget("text") == ROLL_UP

    panel.toggle_minimized()

    assert panel._roll.cget("text") == UNROLL


def test_a_minimized_panel_has_no_resize_corner(board):
    """There is nothing under the title bar to resize, and the corner would hang off the panel."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(50, 50)

    panel.toggle_minimized()

    assert not panel._grip.place_info()


def test_the_resize_corner_comes_back_when_the_panel_unrolls(board):
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(50, 50)
    panel.toggle_minimized()

    panel.toggle_minimized()

    assert panel._grip.place_info()


def test_a_minimized_panel_does_not_resize(board):
    """The corner is not on a rolled-up panel to be dragged, and a resize behind its back would
    unroll it into a size the player never asked for."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(50, 50)
    panel.toggle_minimized()

    panel._grab(_drag(500, 500))
    panel._resize(_drag(560, 530))
    panel.toggle_minimized()

    assert _geometry(panel)[2:] == (400, 300)


def test_a_reopened_panel_keeps_the_size_the_player_gave_it(board):
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(50, 50)
    panel._grab(_drag(500, 500))
    panel._resize(_drag(560, 530))
    panel.close()

    panel.open_at(50, 50)

    assert _geometry(panel)[2:] == (460, 330)


def test_a_panel_closed_while_rolled_up_reopens_rolled_up(board):
    """Rolling it away is the player saying they want the board, and an attack ending is no reason
    to overrule that when the next one starts."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(50, 50)
    panel.toggle_minimized()
    panel.close()

    panel.open_at(50, 50)

    assert panel.minimized
    assert _geometry(panel)[3] == ROLLED_H


def test_reopening_leaves_the_panel_where_the_player_dragged_it(board):
    """Opening is said on every refresh, so a panel that took the opening spot each time would walk
    back out from under the player as they moved it."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(100, 100)
    panel._grab(_drag(500, 500))
    panel._drag(_drag(560, 560))

    panel.open_at(100, 100)

    assert _geometry(panel)[:2] == (160, 160)


def test_a_reopened_panel_keeps_the_place_it_was_closed_at(board):
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(100, 100)
    panel._grab(_drag(500, 500))
    panel._drag(_drag(560, 560))
    panel.close()

    panel.open_at(100, 100)

    assert _geometry(panel)[:2] == (160, 160)


def test_a_board_that_shrinks_brings_the_panel_back_with_it(board):
    """The one state in this design that is not self-correcting if the clamp only runs on a drag:
    the panel is left where a larger board allowed, off the smaller one, and the title bar that
    would drag it back is off the edge too."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(100, 100)
    panel._grab(_drag(500, 500))
    panel._drag(_drag(5000, 5000))

    _shrink(panel, board, 400, 300)

    x, y, _, _ = _geometry(panel)
    assert (x, y) == (400 - KEEP_VISIBLE, 300 - ROLLED_H)


def test_a_panel_stranded_off_the_board_is_recovered_rather_than_reopened_off_it(board):
    """Reopening keeps the player's placement, so a placement gone bad has to be corrected where it
    is stored rather than only on the way out."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_at(100, 100)
    panel._grab(_drag(500, 500))
    panel._drag(_drag(5000, 5000))
    _shrink(panel, board, 400, 300)
    panel.close()

    panel.open_at(10, 10)

    x, y, _, _ = _geometry(panel)
    assert (x, y) == (400 - KEEP_VISIBLE, 300 - ROLLED_H)


def test_opening_over_a_box_takes_that_box(board):
    panel = FloatingPanel(board, "Attack", width=400, height=300)

    panel.open_over(0, 0, 800, 250)

    assert _geometry(panel) == (0, 0, 800, 250)


def test_a_box_larger_than_the_board_is_trimmed_to_it(board):
    """Otherwise the panel opens with its resize corner past the edge and cannot be shrunk to fit."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)

    panel.open_over(0, 0, 2000, 1500)

    assert _geometry(panel) == (0, 0, 800, 600)


def test_opening_over_a_box_does_not_resize_a_panel_already_on_the_board(board):
    """Opening is said on every refresh, so a box applied each time would snap the panel back out
    from under a player who has just resized it."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_over(0, 0, 400, 250)

    panel.open_over(0, 0, 700, 500)

    assert _geometry(panel) == (0, 0, 400, 250)


def test_opening_over_a_box_leaves_a_panel_the_player_has_already_placed_alone(board):
    """The box is where it starts, not where it belongs — a size the player chose is theirs, and an
    attack ending is no reason to take it back."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    panel.open_over(0, 0, 400, 250)  # narrower than the board, so there is room to grow
    panel._grab(_drag(500, 500))
    panel._resize(_drag(560, 530))
    panel.close()

    panel.open_over(0, 0, 400, 250)

    assert _geometry(panel)[2:] == (460, 280)


def test_the_title_bar_is_what_carries_the_drag(board):
    """Every other drag test calls the handler, so nothing else notices the day <B1-Motion> is bound
    to the wrong widget and the bar stops moving the panel."""
    panel = FloatingPanel(board, "Attack", width=400, height=300)
    bar = panel.winfo_children()[0]

    assert bar.bind("<Button-1>")
    assert bar.bind("<B1-Motion>")


def test_the_panel_listens_for_the_board_resizing(board):
    """The clamp is only as good as the notice that runs it, and a board shrinking is the one
    change to a panel's position that the player did not make and cannot see coming."""
    FloatingPanel(board, "Attack", width=400, height=300)

    assert board.bind("<Configure>")

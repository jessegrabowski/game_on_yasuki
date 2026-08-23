import pytest
from numpy.random import default_rng

import yasuki_gui.config as gui_config
import yasuki_gui.ui.game_window as game_window_mod
from yasuki_core.engine.players import PlayerId
from yasuki_gui.session import build_demo_state
from yasuki_gui.ui.game_window import GameWindow

# Every widget the window promises a collaborator. Named rather than discovered, so a widget
# dropped from the class fails here instead of quietly leaving the tuple shorter.
EXPOSED_WIDGETS = (
    "root",
    "sidebar",
    "content",
    "field",
    "phase_bar",
    "prompt_box",
    "opponent_panel",
    "human_panel",
    "menubar",
)


@pytest.fixture
def window():
    state, seat = build_demo_state(default_rng(7))
    built = GameWindow(state, seat)
    try:
        yield built
    finally:
        built.root.destroy()


@pytest.mark.parametrize("name", EXPOSED_WIDGETS)
def test_every_exposed_widget_is_built_by_the_constructor(window, name):
    """The point of the class: a collaborator handed the window cannot read a widget that has not
    been constructed, so the late-binding failure mode is gone rather than merely avoided."""
    assert getattr(window, name) is not None


def test_the_board_opens_on_the_table_it_was_handed(window):
    """The window renders a game rather than dealing one. The table is a constructor argument
    rather than a later assignment because a panel reads its seat's name as it is built, which is
    what this asserts — a window handed the table afterwards would show an empty panel."""
    state, _ = build_demo_state(default_rng(7))

    assert window.human_panel._name_label.cget("text") == state.seats[PlayerId.P1].name


def _rows(window) -> tuple[int, int]:
    """The sidebar grid rows the opponent and human panels sit in."""
    return (
        window.opponent_panel.grid_info()["row"],
        window.human_panel.grid_info()["row"],
    )


def test_construction_seats_the_human_at_the_bottom(window):
    """The sidebar is laid out by the constructor, so a caller never has to place it."""
    opponent_row, human_row = _rows(window)

    assert human_row > opponent_row


def test_relayout_swaps_the_panels_when_the_viewed_seat_changes(window):
    """The debug seat toggle moves the seat being played to the bottom of the column. Driven
    through the board's hook rather than the method, since the toggle reaches the window only if
    the window installed itself there."""
    before = _rows(window)
    window.field.seat = PlayerId.P2

    window.field.on_local_player_changed()

    assert _rows(window) == before[::-1]


def test_relayout_resyncs_the_panels_against_the_board(window):
    """Layout alone is not enough — the numbers a panel shows have to follow the table under it,
    or a deck load leaves the previous game's honor on screen."""
    window.field.state.seats[PlayerId.P1].honor = 99

    window.relayout_panels()

    assert window.human_panel._honor_text.get() == "Honor 99"


def test_the_profile_lands_on_the_panel_of_the_seat_being_played(window):
    """Driven through the board's hook, which is how the preferences dialog reaches the panels."""
    window.field.profile_name = "Ada"
    window.field.profile_avatar = None

    window.field.apply_profile_to_panels()

    assert window.human_panel._name_label.cget("text") == "Ada"


def test_the_profile_follows_the_toggled_seat(window):
    """Which panel is "yours" is decided by the seat on the board, so the debug toggle moves where
    the profile is written as well as where the panel sits."""
    window.field.seat = PlayerId.P2
    window.field.profile_name = "Ada"
    window.field.profile_avatar = None

    window.field.apply_profile_to_panels()

    assert window.opponent_panel._name_label.cget("text") == "Ada"


def test_a_local_override_turns_the_debug_flag_on_for_the_modules_that_read_it(monkeypatch):
    """``controller`` reads ``gui_config.DEBUG_MODE`` at click time rather than importing it, so
    the override has to reach the module attribute and not only the window."""
    monkeypatch.setattr(gui_config, "DEBUG_MODE", False)
    monkeypatch.setattr(game_window_mod, "LOCAL_DEBUG_OVERRIDE", True)
    state, seat = build_demo_state(default_rng(7))

    built = GameWindow(state, seat)
    try:
        assert built.debug
        assert gui_config.DEBUG_MODE
        assert "DEBUG" in built.root.title()
    finally:
        built.root.destroy()

import tkinter as tk

import pytest
from numpy.random import default_rng

import yasuki_gui.config as gui_config
import yasuki_gui.ui.game_window as game_window_mod
from yasuki_core.engine.players import PlayerId
from yasuki_gui.session import build_demo_state
from yasuki_gui.ui.card_preview import CardPreview
from yasuki_gui.ui.game_window import GameWindow

from tests.yasuki_core.engine.builders import personality
from tests.yasuki_gui.conftest import DummyEventNamespace, PreviewOnlyImages, menubar_cascades

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
    """The window renders a game rather than dealing one: the table is a constructor argument, not
    a later assignment, since a panel reads its seat's name as it is built."""
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
    """Layout alone is not enough. The numbers a panel shows have to follow the table under it,
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
        assert "Debug" in menubar_cascades(built.menubar)
    finally:
        built.root.destroy()


def test_the_board_previews_through_the_window_preview(window):
    """The board dismisses the preview on its own keys and clicks, so it has to be the same one the
    view key opens."""
    assert window.field.preview is window.card_preview


def _press_view_key(window, x_root, y_root):
    window._on_view_key(DummyEventNamespace(x_root=x_root, y_root=y_root))


def _strip_card_point(window):
    window.show_cards([personality("hida")], "Fate Discard")
    window.root.update_idletasks()
    visual = window.card_strip._drawn["card:hida"]
    canvas = window.card_strip.canvas
    return canvas.winfo_rootx() + visual.x, canvas.winfo_rooty() + visual.y


def test_the_view_key_enlarges_a_strip_card_and_puts_it_away_again(window):
    """One handler owns the key across the board and every panel, so a press over a panel card
    opens the preview and the next press closes it, wherever the pointer is."""
    art = tk.PhotoImage(master=window.root, width=1, height=1)
    window.card_preview = CardPreview(window.root, PreviewOnlyImages(art))
    point = _strip_card_point(window)

    _press_view_key(window, *point)
    assert window.card_preview.showing

    _press_view_key(window, *point)
    assert not window.card_preview.showing


def test_the_view_key_over_a_panel_puts_away_a_preview_the_board_opened(window):
    art = tk.PhotoImage(master=window.root, width=1, height=1)
    window.card_preview = CardPreview(window.root, PreviewOnlyImages(art))
    window.card_preview.show(personality("board"), 0, 0)

    _press_view_key(window, *_strip_card_point(window))

    assert not window.card_preview.showing


def test_the_view_key_off_the_board_opens_nothing(window):
    art = tk.PhotoImage(master=window.root, width=1, height=1)
    window.card_preview = CardPreview(window.root, PreviewOnlyImages(art))

    _press_view_key(window, window.field.winfo_rootx() - 50, window.field.winfo_rooty() - 50)

    assert not window.card_preview.showing


def test_the_view_key_is_bound_once_for_the_whole_window(window):
    """Bound on the ``all`` tag by the window, not by the board or by each panel, so there is one
    handler to reason about however many panels are open."""
    key = f"<KeyPress-{window.field._hotkeys.view}>"

    assert window.root.bind_all(key)
    assert not window.card_strip.bind(key)
    assert not window.battle_view.bind(key)


def test_reconfiguring_the_board_keys_leaves_the_view_key_bound(window):
    """The board rebinds its own keys by replacing the app-wide script for each. The view key is
    not one of them, so a hotkeys change cannot drop it."""
    key = f"<KeyPress-{window.field._hotkeys.view}>"
    before = window.root.bind_all(key)

    window.field.configure_hotkeys(window.field._hotkeys)

    assert window.root.bind_all(key) == before


def test_binding_points_each_debug_hook_at_its_own_presenter_method(window):
    called = []

    # bind_to wires every presenter method, so the stub answers to any name with a recorder.
    class _Presenter:
        def __getattr__(self, name):
            return lambda *args: called.append(name)

    window.bind_to(_Presenter())
    window.field.on_debug_gold()
    window.field.on_debug_card_to_hand()
    window.field.on_debug_card_to_province()

    assert called == ["debug_gold", "debug_card_to_hand", "debug_card_to_province"]

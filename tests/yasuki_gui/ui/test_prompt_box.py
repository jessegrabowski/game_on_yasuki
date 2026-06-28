import tkinter as tk

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState
from yasuki_core.engine.session import EngineSession
from yasuki_gui.ui.prompt_box import PromptBox


@pytest.fixture
def root():
    r = tk.Tk()
    r.withdraw()
    yield r
    r.destroy()


def _view():
    session = EngineSession.start(TableState.empty_two_seat(), PlayerId.P1)
    session.game.add_gold(PlayerId.P1, 5)
    return session.project(PlayerId.P1)


def _buttons(box: PromptBox) -> list[tk.Button]:
    return [w for w in box._actions.winfo_children() if isinstance(w, tk.Button)]


def test_show_renders_the_status_with_turn_and_viewer_gold(root):
    box = PromptBox(root)
    box.show(_view(), "Your turn", [])
    text = box._status.cget("text")
    assert "Turn 1" in text
    assert "Your turn" in text
    assert "Gold: 5" in text


def test_show_renders_a_button_per_spec_and_invokes_its_command(root):
    clicks = []
    box = PromptBox(root)
    box.show(_view(), "Your turn", [("Pass", lambda: clicks.append("pass"), True)])

    buttons = _buttons(box)
    assert [b.cget("text") for b in buttons] == ["Pass"]
    buttons[0].invoke()
    assert clicks == ["pass"]


def test_show_disables_buttons_marked_not_enabled(root):
    box = PromptBox(root)
    box.show(_view(), "discard 1 card(s)", [("Discard", lambda: None, False)])
    assert str(_buttons(box)[0].cget("state")) == "disabled"


def test_show_replaces_the_previous_buttons(root):
    box = PromptBox(root)
    box.show(_view(), "Your turn", [("Pass", lambda: None, True)])
    box.show(_view(), "Opponent's turn", [])
    assert _buttons(box) == []

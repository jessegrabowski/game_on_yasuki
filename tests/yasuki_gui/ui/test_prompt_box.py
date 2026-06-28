import tkinter as tk

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState
from yasuki_core.engine.session import EngineSession, LegalAction
from yasuki_gui.ui.prompt_box import PromptBox


@pytest.fixture
def root():
    r = tk.Tk()
    r.withdraw()
    yield r
    r.destroy()


def _view(active: PlayerId):
    session = EngineSession.start(TableState.empty_two_seat(), PlayerId.P1)
    session.game.active = active
    return session.project(PlayerId.P1)


def _buttons(box: PromptBox) -> list[tk.Button]:
    return [w for w in box._actions.winfo_children() if isinstance(w, tk.Button)]


def test_legal_actions_render_as_buttons_that_invoke_the_callback(root):
    chosen = []
    box = PromptBox(root, chosen.append)
    box.refresh(_view(PlayerId.P1), [LegalAction.PASS])

    buttons = _buttons(box)
    assert [b.cget("text") for b in buttons] == ["Pass"]
    buttons[0].invoke()
    assert chosen == [LegalAction.PASS]


def test_status_names_whose_turn_and_clears_actions_on_the_opponents_turn(root):
    box = PromptBox(root, lambda action: None)

    box.refresh(_view(PlayerId.P1), [LegalAction.PASS])
    assert "Your turn" in box._status.cget("text")
    assert _buttons(box)

    box.refresh(_view(PlayerId.P2), [])  # opponent holds the turn, no legal actions
    assert "Opponent's turn" in box._status.cget("text")
    assert _buttons(box) == []


def test_discard_prompt_enables_confirm_only_at_the_exact_count(root):
    confirmed = []
    box = PromptBox(root, lambda action: None)
    view = _view(PlayerId.P1)

    box.prompt_discard(view, needed=2, selected=1, on_confirm=lambda: confirmed.append(1))
    discard = _buttons(box)[0]
    assert discard.cget("text") == "Discard"
    assert "discard 2" in box._status.cget("text").lower()
    assert str(discard.cget("state")) == "disabled"  # 1 of 2 chosen

    box.prompt_discard(view, needed=2, selected=2, on_confirm=lambda: confirmed.append(1))
    discard = _buttons(box)[0]
    assert str(discard.cget("state")) == "normal"
    discard.invoke()
    assert confirmed == [1]

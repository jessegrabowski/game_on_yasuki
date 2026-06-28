import tkinter as tk

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState
from yasuki_core.engine.rules.state import Phase
from yasuki_core.engine.session import EngineSession, LegalAction
from yasuki_gui.ui.phase_bar import PhaseBar


@pytest.fixture
def root():
    r = tk.Tk()
    r.withdraw()
    yield r
    r.destroy()


def _view(active: PlayerId, phase: Phase = Phase.ACTION):
    session = EngineSession.start(TableState.empty_two_seat(), PlayerId.P1)
    session.game.active = active
    session.game.phase = phase
    return session.project(PlayerId.P1)


def _buttons(bar: PhaseBar) -> list[tk.Button]:
    return [w for w in bar._actions.winfo_children() if isinstance(w, tk.Button)]


def test_legal_actions_render_as_buttons_that_invoke_the_callback(root):
    chosen = []
    bar = PhaseBar(root, chosen.append)
    bar.refresh(_view(PlayerId.P1), [LegalAction.PASS])

    buttons = _buttons(bar)
    assert [b.cget("text") for b in buttons] == ["Pass"]
    buttons[0].invoke()
    assert chosen == [LegalAction.PASS]


def test_no_buttons_and_opponent_label_when_it_is_not_your_turn(root):
    bar = PhaseBar(root, lambda action: None)

    bar.refresh(_view(PlayerId.P1), [LegalAction.PASS])
    assert bar._turn.cget("text") == "Turn 1"
    assert bar._whose.cget("text") == "Your turn"
    assert _buttons(bar)  # actions offered on your turn

    bar.refresh(_view(PlayerId.P2), [])  # opponent holds the turn, no legal actions
    assert bar._whose.cget("text") == "Opponent's turn"
    assert _buttons(bar) == []

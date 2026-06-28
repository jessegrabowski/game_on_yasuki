import tkinter as tk

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState
from yasuki_core.engine.rules.state import Phase
from yasuki_core.engine.session import EngineSession
from yasuki_gui.ui.phase_bar import PhaseBar


@pytest.fixture
def root():
    r = tk.Tk()
    r.withdraw()
    yield r
    r.destroy()


def _view(phase: Phase):
    session = EngineSession.start(TableState.empty_two_seat(), PlayerId.P1)
    session.game.phase = phase
    return session.project(PlayerId.P1)


def test_advance_button_invokes_the_callback(root):
    calls = []
    bar = PhaseBar(root, lambda: calls.append(1))
    bar._advance.invoke()
    assert calls == [1]


def test_refresh_shows_turn_and_contextual_button_label(root):
    bar = PhaseBar(root, lambda: None)

    bar.refresh(_view(Phase.ACTION))
    assert bar._turn.cget("text") == "Turn 1"
    assert "Next Phase" in bar._advance.cget("text")

    # On the last phase the button reads as ending the turn.
    bar.refresh(_view(Phase.DYNASTY))
    assert "End Turn" in bar._advance.cget("text")

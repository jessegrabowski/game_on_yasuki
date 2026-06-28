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


def test_only_the_current_phase_is_highlighted(root):
    bar = PhaseBar(root)
    bar.refresh(_view(Phase.ATTACK))

    chips = bar._chips
    assert chips[Phase.ATTACK].cget("text").endswith("Attack")
    assert chips[Phase.ATTACK].cget("text").startswith("▶")  # the active marker
    assert chips[Phase.ACTION].cget("text") == "Action"  # dimmed, unmarked
    # The active chip is filled; the others are not.
    assert chips[Phase.ATTACK].cget("bg") != chips[Phase.ACTION].cget("bg")

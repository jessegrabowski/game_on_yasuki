import gc

import pytest
import tkinter as tk

from numpy.random import default_rng

from yasuki_gui.config import Hotkeys
from yasuki_gui.field_view import FieldView
from yasuki_gui.session import build_demo_state


@pytest.fixture(autouse=True)
def _reclaim_tk_cycles_on_main_thread():
    """Collect each GUI test's tkinter/PIL reference cycles on the main thread.

    tkinter widgets and PIL ``PhotoImage``s form cycles that only generational GC reclaims. Left as
    garbage, that GC can later fire on a worker thread — the web suite runs DB queries via
    ``to_thread`` in the same process — and run their Tcl finalizers off the interpreter's thread,
    aborting the process with ``Tcl_AsyncDelete: async handler deleted by the wrong thread``.
    Reclaiming them here, on the main thread after each test, leaves nothing for a worker to finalize.
    """
    yield
    gc.collect()


@pytest.fixture(autouse=True)
def _keep_tk_windows_off_screen(monkeypatch):
    """Withdraw every Tk window a GUI test builds — roots and Toplevels alike, wherever it builds
    them.

    A mapped window takes the keyboard focus from whatever the developer is doing, and the suite
    makes dozens. Patching the constructors covers windows created inside a test body as well as in
    a fixture, so a new test cannot reintroduce the problem by forgetting to withdraw.

    Toplevels are included because a dialog maps as soon as anything pumps the event loop — which
    a dialog sizing its own scroll region does — and the test that opened it has no handle to close
    it again. Withdrawing costs nothing: geometry is still computed on idle, so the widgets under
    test measure exactly as they would on screen.
    """
    real_tk = tk.Tk

    def withdrawn(*args, **kwargs):
        root = real_tk(*args, **kwargs)
        root.withdraw()
        return root

    real_toplevel = tk.Toplevel

    def withdrawn_toplevel(*args, **kwargs):
        win = real_toplevel(*args, **kwargs)
        win.withdraw()
        return win

    monkeypatch.setattr(tk, "Tk", withdrawn)
    monkeypatch.setattr(tk, "Toplevel", withdrawn_toplevel)


@pytest.fixture
def root():
    r = tk.Tk()
    r.withdraw()
    try:
        yield r
    finally:
        r.destroy()


@pytest.fixture
def field(root):
    f = FieldView(root, width=600, height=400)
    f.pack()
    root.update_idletasks()
    root.update()
    f.configure_hotkeys(Hotkeys())
    return f


@pytest.fixture
def loaded(root):
    """A FieldView with a full demo TableState loaded, viewed from the human seat (P1). Sized large
    enough that the two seats' rows do not collapse onto each other."""
    f = FieldView(root, width=1000, height=800)
    f.pack()
    root.update_idletasks()
    root.update()
    f.configure_hotkeys(Hotkeys())
    state, seat = build_demo_state(default_rng(7))
    f.load_state(state, seat)
    return f, state


class DummyEventNamespace(tk.Event):
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

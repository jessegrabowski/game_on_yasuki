import gc

import pytest
import tkinter as tk

from yasuki_gui.field_view import FieldView
from yasuki_gui.config import Hotkeys


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


class DummyEventNamespace(tk.Event):
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

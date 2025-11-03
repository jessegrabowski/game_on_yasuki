import pytest
import tkinter as tk

from app.gui.field_view import GameField
from app.gui.config import Hotkeys


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
    f = GameField(root, width=600, height=400)
    f.pack()
    root.update_idletasks()
    root.update()
    f.configure_hotkeys(Hotkeys())
    return f


class DummyEventNamespace(tk.Event):
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

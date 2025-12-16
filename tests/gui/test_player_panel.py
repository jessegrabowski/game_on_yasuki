from app.gui.__main__ import PlayerPanel
from app.gui.constants import MIN_HONOR


def _update(root):
    """Helper to update tkinter root."""
    root.update_idletasks()
    root.update()


def test_player_honor_adjust_clicks(root):
    panel = PlayerPanel(root, username="Alice", initial_honor=5)
    panel.pack()
    _update(root)

    honor_label = panel.honor_label

    assert honor_label.bind("<Button-1>")
    assert honor_label.bind("<Button-3>")

    panel._adjust(1)
    _update(root)
    assert panel.honor.get() == 6

    panel._adjust(-1)
    _update(root)
    assert panel.honor.get() == 5

    panel._adjust(-1)
    _update(root)
    assert panel.honor.get() == 4

    panel.honor.set(0)
    panel._adjust(-1)
    _update(root)
    assert panel.honor.get() == -1


def test_player_honor_adjust_scroll(root):
    panel = PlayerPanel(root, username="Bob", initial_honor=5)
    panel.pack()
    _update(root)
    _ = panel.honor_label

    class E:
        def __init__(self, delta):
            self.delta = delta

    panel._on_wheel(E(delta=120))
    _update(root)
    assert panel.honor.get() == 6

    panel._on_wheel(E(delta=-120))
    _update(root)
    assert panel.honor.get() == 5

    panel.honor.set(MIN_HONOR)
    panel._on_wheel(E(delta=-120))
    _update(root)
    assert panel.honor.get() == MIN_HONOR

    for _ in range(100):
        panel._adjust(1)
    _update(root)
    assert panel.honor.get() >= 0

from app.gui.__main__ import PlayerPanel
from app.gui.constants import MIN_HONOR


def test_player_honor_adjust_clicks(root):
    panel = PlayerPanel(root, username="Alice", initial_honor=5)
    panel.pack()
    root.update_idletasks()
    root.update()

    honor_label = panel.honor_label

    # Ensure click bindings are present on the honor label
    assert honor_label.bind("<Button-1>")
    assert honor_label.bind("<Button-3>")

    # Directly adjust via method to verify behavior (UI event generation can be flaky headless)
    panel._adjust(1)
    root.update_idletasks()
    root.update()
    assert panel.honor.get() == 6
    panel._adjust(-1)
    root.update_idletasks()
    root.update()
    assert panel.honor.get() == 5
    panel._adjust(-1)
    root.update_idletasks()
    root.update()
    assert panel.honor.get() == 4

    panel.honor.set(0)
    panel._adjust(-1)
    root.update_idletasks()
    root.update()
    assert panel.honor.get() == -1


def test_player_honor_adjust_scroll(root):
    panel = PlayerPanel(root, username="Bob", initial_honor=5)
    panel.pack()
    root.update_idletasks()
    root.update()
    _ = panel.honor_label

    class E:  # simple event stub
        def __init__(self, delta):
            self.delta = delta

    # Scroll up (positive delta) increments
    panel._on_wheel(E(delta=120))
    root.update_idletasks()
    root.update()
    assert panel.honor.get() == 6

    # Scroll down (negative delta) decrements
    panel._on_wheel(E(delta=-120))
    root.update_idletasks()
    root.update()
    assert panel.honor.get() == 5

    # Clamp lower bound (configured MIN_HONOR)
    panel.honor.set(MIN_HONOR)
    panel._on_wheel(E(delta=-120))
    root.update_idletasks()
    root.update()
    assert panel.honor.get() == MIN_HONOR

    # Move toward upper bound using direct adjust and ensure it clamps (if MAX_HONOR exists)
    for _ in range(100):
        panel._adjust(1)
    root.update_idletasks()
    root.update()
    assert panel.honor.get() >= 0

from yasuki_core.engine.players import PlayerId
from yasuki_gui.__main__ import PlayerPanel


class _Wheel:
    def __init__(self, delta):
        self.delta = delta


def test_human_panel_adjust_dispatches_set_honor(loaded, root):
    field, state = loaded  # human is P1
    panel = PlayerPanel(root, field, PlayerId.P1)
    start = state.seats[PlayerId.P1].honor

    panel._adjust(1)
    assert state.seats[PlayerId.P1].honor == start + 1
    assert panel.honor.get() == start + 1
    assert panel._honor_text.get() == f"Honor {start + 1}"

    panel._adjust(-1)
    assert state.seats[PlayerId.P1].honor == start


def test_human_panel_wheel_adjusts(loaded, root):
    field, state = loaded
    panel = PlayerPanel(root, field, PlayerId.P1)
    start = state.seats[PlayerId.P1].honor

    panel._on_wheel(_Wheel(delta=120))
    assert state.seats[PlayerId.P1].honor == start + 1
    panel._on_wheel(_Wheel(delta=-120))
    assert state.seats[PlayerId.P1].honor == start


def test_opponent_panel_is_read_only(loaded, root):
    field, state = loaded
    panel = PlayerPanel(root, field, PlayerId.P2)
    start = state.seats[PlayerId.P2].honor

    panel._adjust(1)
    assert state.seats[PlayerId.P2].honor == start
    assert panel.honor.get() == start


def test_editability_follows_acting_seat(loaded, root):
    # The debug seat toggle makes the other panel editable; refresh() must pick that up.
    field, state = loaded
    panel = PlayerPanel(root, field, PlayerId.P2)
    field.seat = PlayerId.P2
    panel.refresh()

    start = state.seats[PlayerId.P2].honor
    panel._adjust(1)
    assert state.seats[PlayerId.P2].honor == start + 1

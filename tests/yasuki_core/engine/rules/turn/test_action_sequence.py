import pytest

from yasuki_core.engine.rules.turn import action_sequence

from tests.yasuki_core.engine.builders import two_seat_game


def test_an_unhandled_action_is_refused_rather_than_ignored():
    # perform is the entry point for a player's chosen action. Falling through would accept the
    # action and silently do nothing, which is indistinguishable from a legal no-op.
    class Unregistered:
        pass

    with pytest.raises(ValueError, match="no handler for action"):
        action_sequence.perform(two_seat_game(), Unregistered())

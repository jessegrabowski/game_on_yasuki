import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Recruit
from yasuki_core.engine.session import EngineSession

from tests.yasuki_core.engine.builders import (
    dealt_table,
    end_phase,
    holding,
    pay,
    province_card,
    put_in_play,
)

P1 = PlayerId.P1
P2 = PlayerId.P2


def _recruit_pending(cost: int, production: int, seat: PlayerId = P1) -> EngineSession:
    """A game paused on ``seat``'s payment for a cost-``cost`` Holding, with one producer able to
    cover it."""
    state = dealt_table()
    put_in_play(state, holding("mine", owner=seat, gold_production=production))
    session = EngineSession.start(state, seat)
    province_card(session.game, "target", seat=seat, gold_cost=cost)
    end_phase(session)
    end_phase(session)
    session.act(seat, Recruit("target"))
    return session


def test_pay_covers_the_cost_and_bows_the_producer():
    session = _recruit_pending(cost=3, production=4)

    pay(session, P1)

    assert session.game.pending is None
    assert session.game.table.cards_by_id["mine"].bowed
    assert session.game.table.cards_by_id["target"] in session.game.table.battlefield.cards


def test_pay_refuses_when_no_payment_is_pending():
    """The guard is the point: a test that has drifted past its payment should fail at the drift,
    not at whatever assertion happens to notice later."""
    session = _recruit_pending(cost=3, production=4)
    pay(session, P1)

    with pytest.raises(AssertionError, match="no payment pending"):
        pay(session, P1)


def test_pay_refuses_a_payment_another_seat_owes():
    """Naming the wrong seat has to fail rather than quietly do nothing, or a test drifts on with
    the cost still unpaid and fails somewhere that says nothing about why."""
    session = _recruit_pending(cost=3, production=4, seat=P2)

    with pytest.raises(AssertionError, match="P2's, not P1's"):
        pay(session, P1)

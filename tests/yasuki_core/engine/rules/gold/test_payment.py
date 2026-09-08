from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.gold.payment import (
    can_afford,
    payment_in_flight,
    refusal_would_strand,
)
from yasuki_core.engine.rules.gold.self_grants import GOLD_SELF_GRANT, register_self_grant
from yasuki_core.engine.rules.work import ContinuePayment

from tests.yasuki_core.engine.builders import holding, put_in_play, two_seat_game


def test_affordability_counts_the_pool_and_every_unbowed_producer():
    game = two_seat_game()
    game.gold[PlayerId.P1] = 1
    put_in_play(game, holding("P1-farm", owner=PlayerId.P1, gold_production=2))
    bowed = put_in_play(game, holding("P1-bowed", owner=PlayerId.P1, gold_production=4))
    bowed.bow()
    put_in_play(game, holding("P2-farm", owner=PlayerId.P2, gold_production=9))

    assert can_afford(game, PlayerId.P1, 3) is True
    assert can_afford(game, PlayerId.P1, 4) is False


def test_a_producer_the_cost_itself_bows_cannot_also_pay_for_it():
    # An ability priced "bow this Holding" cannot spend the same bow twice, so counting the producer
    # would offer a purchase the seat provably cannot complete.
    game = two_seat_game()
    farm = put_in_play(game, holding("P1-farm", owner=PlayerId.P1, gold_production=2))

    assert can_afford(game, PlayerId.P1, 2) is True
    assert can_afford(game, PlayerId.P1, 2, bowed_by_cost=frozenset({farm.id})) is False


def test_nothing_is_stranded_when_no_payment_is_in_flight():
    game = two_seat_game()

    assert payment_in_flight(game, PlayerId.P1) is None
    assert refusal_would_strand(game, PlayerId.P1, 2) is False


def test_refusing_a_grant_the_cost_needs_would_strand_the_payment():
    """Affordability counts a self-grant, so announcing a purchase only that grant reaches commits
    the seat to taking it: declining is no longer a way out and cancelling is."""
    game = two_seat_game()
    game.gold[PlayerId.P1] = 0
    put_in_play(
        game, holding("P1-mine", owner=PlayerId.P1, printed_id="strand_probe", gold_production=1)
    )
    register_self_grant("strand_probe", 2)
    game.stack.append(ContinuePayment(seat=PlayerId.P1, amount=3, label="a purchase"))

    try:
        assert refusal_would_strand(game, PlayerId.P1, 2) is True
        assert refusal_would_strand(game, PlayerId.P1, 0) is False
    finally:
        GOLD_SELF_GRANT.pop("strand_probe", None)

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.decisions import ChoosePayment, DiscardToHandSize, DecisionResponse

_HAND = ("a", "b", "c")


def test_discard_accepts_exactly_count_distinct_candidates():
    request = DiscardToHandSize(PlayerId.P1, _HAND, count=2)
    assert request.accepts(DecisionResponse(("a", "b"))) is True


def test_discard_rejects_wrong_number_of_choices():
    request = DiscardToHandSize(PlayerId.P1, _HAND, count=2)
    assert request.accepts(DecisionResponse(("a",))) is False
    assert request.accepts(DecisionResponse(("a", "b", "c"))) is False


def test_discard_rejects_duplicate_choices():
    request = DiscardToHandSize(PlayerId.P1, _HAND, count=2)
    # Two slots filled by the same card is not two discards.
    assert request.accepts(DecisionResponse(("a", "a"))) is False


def test_discard_rejects_choices_outside_the_candidates():
    request = DiscardToHandSize(PlayerId.P1, _HAND, count=2)
    assert request.accepts(DecisionResponse(("a", "z"))) is False  # z is not a candidate


def test_discard_of_zero_accepts_only_an_empty_answer():
    request = DiscardToHandSize(PlayerId.P1, _HAND, count=0)
    assert request.accepts(DecisionResponse(())) is True
    assert request.accepts(DecisionResponse(("a",))) is False


def _payment(amount: int, available: int, produced) -> ChoosePayment:
    return ChoosePayment(
        PlayerId.P1, tuple(card for card, _ in produced), amount, available, tuple(produced), "Mine"
    )


def test_payment_accepts_when_pool_plus_bowed_producers_cover_the_cost():
    request = _payment(amount=5, available=1, produced=[("sh", 8), ("mine", 2)])
    assert request.accepts(DecisionResponse(("sh",))) is True  # 1 + 8 >= 5
    assert request.accepts(DecisionResponse(("sh", "mine"))) is True  # 1 + 8 + 2 >= 5
    assert request.accepts(DecisionResponse(("mine",))) is False  # 1 + 2 < 5


def test_payment_rejects_when_chosen_producers_fall_short():
    request = _payment(amount=5, available=1, produced=[("mine", 2)])
    assert request.accepts(DecisionResponse(("mine",))) is False  # 1 + 2 < 5
    assert request.accepts(DecisionResponse(())) is False  # 1 < 5


def test_payment_accepts_an_empty_answer_when_the_pool_already_covers_it():
    request = _payment(amount=3, available=4, produced=[("sh", 8)])
    assert request.accepts(DecisionResponse(())) is True  # no need to bow anything


def test_payment_rejects_non_candidate_or_duplicate_sources():
    request = _payment(amount=5, available=0, produced=[("sh", 8)])
    assert request.accepts(DecisionResponse(("ghost",))) is False
    assert request.accepts(DecisionResponse(("sh", "sh"))) is False

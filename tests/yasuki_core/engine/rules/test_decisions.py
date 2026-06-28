from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.decisions import DiscardToHandSize, DecisionResponse

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

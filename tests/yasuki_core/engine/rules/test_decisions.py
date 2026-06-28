from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.decisions import DiscardToHandSize, DecisionResponse


def test_discard_accepts_exactly_count_distinct_choices():
    request = DiscardToHandSize(PlayerId.P1, count=2)
    assert request.accepts(DecisionResponse(("a", "b"))) is True


def test_discard_rejects_wrong_number_of_choices():
    request = DiscardToHandSize(PlayerId.P1, count=2)
    assert request.accepts(DecisionResponse(("a",))) is False
    assert request.accepts(DecisionResponse(("a", "b", "c"))) is False


def test_discard_rejects_duplicate_choices():
    request = DiscardToHandSize(PlayerId.P1, count=2)
    # Two slots filled by the same card is not two discards.
    assert request.accepts(DecisionResponse(("a", "a"))) is False


def test_discard_of_zero_accepts_only_an_empty_answer():
    request = DiscardToHandSize(PlayerId.P1, count=0)
    assert request.accepts(DecisionResponse(())) is True
    assert request.accepts(DecisionResponse(("a",))) is False

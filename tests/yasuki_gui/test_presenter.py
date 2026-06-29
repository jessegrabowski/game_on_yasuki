from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.decisions import ChoosePayment, DiscardToHandSize
from yasuki_gui.__main__ import _describe_decision


def _payment(amount: int, available: int, produced, label: str = "Gold Mine") -> ChoosePayment:
    return ChoosePayment(
        PlayerId.P1, tuple(card for card, _ in produced), amount, available, tuple(produced), label
    )


def test_payment_prompt_decrements_as_producers_are_chosen():
    request = _payment(amount=5, available=1, produced=[("sh", 8)])
    assert _describe_decision(request, ()) == ("Pay 4 gold for Gold Mine", "Pay")
    # Choosing the producer covers the rest, so the prompt reads zero owed.
    assert _describe_decision(request, ("sh",)) == ("Pay 0 gold for Gold Mine", "Pay")


def test_discard_prompt_names_the_count():
    request = DiscardToHandSize(PlayerId.P1, ("a", "b"), count=1)
    assert _describe_decision(request, ()) == ("discard 1 card(s)", "Discard")

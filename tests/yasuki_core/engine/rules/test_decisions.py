import pytest

from yasuki_core.engine.players import PlayerId

# Imported for the prompt registrations the card modules perform on import.
from yasuki_core.engine.rules import cards  # noqa: F401
from yasuki_core.engine.rules.decisions import (
    Confirm,
    DecisionRequest,
    ChooseCards,
    ChoosePayment,
    DecisionResponse,
    DiscardToHandSize,
)
from yasuki_core.engine.rules.triggers import choice_resolver

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


def _payment(amount: int, available: int, produced, boostable=()) -> ChoosePayment:
    return ChoosePayment(
        PlayerId.P1,
        tuple(card for card, _ in produced),
        amount,
        available,
        tuple(produced),
        "Mine",
        target_id="mine",
        boostable=tuple(boostable),
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


def test_only_a_payment_is_cancellable():
    assert _payment(amount=5, available=0, produced=[("sh", 8)]).cancellable is True
    assert DiscardToHandSize(PlayerId.P1, _HAND, count=2).cancellable is False


def _choose(minimum: int, maximum: int) -> ChooseCards:
    return ChooseCards(PlayerId.P1, _HAND, minimum, maximum, resolver="r", source_id="src")


def test_choose_cards_accepts_a_count_within_the_bounds():
    request = _choose(minimum=0, maximum=2)
    assert request.accepts(DecisionResponse(())) is True
    assert request.accepts(DecisionResponse(("a",))) is True
    assert request.accepts(DecisionResponse(("a", "b"))) is True


def test_choose_cards_rejects_more_than_the_maximum():
    request = _choose(minimum=0, maximum=2)
    assert request.accepts(DecisionResponse(("a", "b", "c"))) is False  # the "zero to two" cap


def test_choose_cards_rejects_fewer_than_the_minimum():
    request = _choose(minimum=1, maximum=2)
    assert request.accepts(DecisionResponse(())) is False


def test_choose_cards_rejects_duplicate_or_non_candidate_choices():
    request = _choose(minimum=0, maximum=2)
    assert request.accepts(DecisionResponse(("a", "a"))) is False
    assert request.accepts(DecisionResponse(("z",))) is False  # z is not a candidate


def _every_request_type():
    """The request types the engine defines. Scoped by module so a subclass declared inside a test
    does not register itself into the set under inspection."""
    return [
        cls
        for cls in DecisionRequest.__subclasses__()
        if cls.__module__ == DecisionRequest.__module__
    ]


def test_every_decision_states_its_own_prompt():
    abstract = [
        cls.__name__
        for cls in _every_request_type()
        if getattr(cls.prompt, "__isabstractmethod__", False)
    ]
    assert abstract == []


def test_payment_prompt_counts_down_as_producers_are_picked():
    request = _payment(amount=5, available=1, produced=(("a", 2), ("b", 2)))
    assert request.prompt() == "Pay 4 gold for Mine"
    assert request.prompt(chosen=("a",)) == "Pay 2 gold for Mine"
    assert request.prompt(chosen=("a", "b")) == "Pay 0 gold for Mine"
    assert request.confirm_label == "Pay"


def test_choose_cards_wording_distinguishes_optional_from_required():
    assert _choose(minimum=0, maximum=2).prompt() == "Choose up to 2 card(s)"
    assert _choose(minimum=1, maximum=2).prompt() == "Choose 1 to 2 card(s)"


@choice_resolver("test_prompted", prompt="Put a card on the bottom of your deck")
def _prompted(game, source_id, chosen, seat):
    return []


def test_a_registered_prompt_replaces_the_generic_wording():
    # The generic line names a count and nothing else, which tells a player how many cards to click
    # but never what the choice is for. The two are shown side by side because the fallback has to
    # survive: most choices register no prompt.
    prompted = ChooseCards(PlayerId.P1, _HAND, 0, 2, resolver="test_prompted")

    assert prompted.prompt() == "Put a card on the bottom of your deck"
    assert _choose(minimum=0, maximum=2).prompt() == "Choose up to 2 card(s)"


@pytest.mark.parametrize(
    "resolver, expected",
    [
        ("wheat_farm", "Give a Wealth token to other Farms you control"),
        ("modest_farm_straighten", "Destroy Modest Farm to straighten the card it recruited"),
    ],
)
def test_a_shipped_choice_registers_its_own_wording(resolver, expected):
    # Wording is what a hand-written registration gets wrong without failing anything, so each line
    # is reviewed here rather than only in the diff that first wrote it. Asked through the request
    # the player answers, so a prompt registered under a name nothing looks up still fails.
    request = ChooseCards(PlayerId.P1, _HAND, 0, 2, resolver=resolver)

    assert request.prompt() == expected


def test_confirm_label_defaults_to_confirm():
    assert _choose(minimum=1, maximum=1).confirm_label == "Confirm"


def test_payment_prompt_counts_a_boosted_producer_at_its_higher_yield():
    # Bowing Outlying Farms plain leaves 2 owed; boosting it covers the whole cost.
    request = _payment(amount=4, available=0, produced=[("of", 2)], boostable=[("of", 2)])
    assert request.prompt(chosen=("of",)) == "Pay 2 gold for Mine"
    assert request.prompt(chosen=("of",), boosted=("of",)) == "Pay 0 gold for Mine"


def test_discard_prompt_names_the_count():
    request = DiscardToHandSize(PlayerId.P1, ("a", "b"), count=1)
    assert request.prompt() == "discard 1 card(s)"
    assert request.confirm_label == "Discard"


def test_a_confirm_takes_yes_as_its_subjects_and_no_as_none():
    """The answer is the subjects or nothing, which is what an optional card choice already hands a
    resolver — so asking a question instead of offering a selection changes no resolver."""
    ask = Confirm(
        seat=PlayerId.P1,
        candidates=("farm",),
        question="Destroy Modest Farm to straighten Kobune?",
        resolver="modest_farm_straighten",
    )

    assert ask.accepts(DecisionResponse(("farm",)))  # yes
    assert ask.accepts(DecisionResponse(()))  # no
    assert not ask.accepts(DecisionResponse(("someone-else",)))
    assert not ask.accepts(DecisionResponse(("farm", "farm")))


def test_a_confirm_asks_its_question_verbatim():
    """The wording names the cards, so it is built per use rather than registered per resolver."""
    ask = Confirm(
        seat=PlayerId.P1,
        candidates=("event",),
        question="Shuffle Blessings of the Red Panda Spirit into your deck?",
        resolver="red_panda_reshuffle",
    )

    assert ask.prompt() == "Shuffle Blessings of the Red Panda Spirit into your deck?"

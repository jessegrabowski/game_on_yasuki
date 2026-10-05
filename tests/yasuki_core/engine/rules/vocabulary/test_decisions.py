import pytest

from yasuki_core.engine.players import PlayerId, Rulebook

# Imported for the prompt registrations the card modules perform on import.
from yasuki_core.engine.rules import cards  # noqa: F401
from yasuki_core.engine.rules.vocabulary.decisions import (
    CHOICE_PICKS,
    ChooseOption,
    ArrangeCards,
    ChooseAbilityTarget,
    Confirm,
    DecisionRequest,
    ChooseCards,
    ChooseDiscard,
    ChooseDistribution,
    ChoosePayment,
    DecisionResponse,
    OneGroup,
    TotalAtMost,
    answerable,
    within_reach,
)
from yasuki_core.engine.rules.triggers import choice_resolver

_HAND = ("a", "b", "c")


def _discard(count: int, *, seat: PlayerId = PlayerId.P1) -> ChooseDiscard:
    return ChooseDiscard(
        seat, _HAND, count=count, holder=PlayerId.P1, cause=Rulebook.MAXIMUM_HAND_SIZE
    )


def test_discard_accepts_exactly_count_distinct_candidates():
    request = _discard(2)
    assert request.accepts(DecisionResponse(("a", "b"))) is True


def test_discard_rejects_wrong_number_of_choices():
    request = _discard(2)
    assert request.accepts(DecisionResponse(("a",))) is False
    assert request.accepts(DecisionResponse(("a", "b", "c"))) is False


def test_discard_rejects_duplicate_choices():
    request = _discard(2)
    # Two slots filled by the same card is not two discards.
    assert request.accepts(DecisionResponse(("a", "a"))) is False


def test_discard_rejects_choices_outside_the_candidates():
    request = _discard(2)
    assert request.accepts(DecisionResponse(("a", "z"))) is False  # z is not a candidate


def test_discard_of_zero_accepts_only_an_empty_answer():
    request = _discard(0)
    assert request.accepts(DecisionResponse(())) is True
    assert request.accepts(DecisionResponse(("a",))) is False


def _payment(amount: int, available: int, produced, grantable=()) -> ChoosePayment:
    return ChoosePayment(
        PlayerId.P1,
        tuple(card for card, _ in produced),
        amount,
        available,
        tuple(produced),
        "Mine",
        target_id="mine",
        grantable=tuple(grantable),
    )


def test_payment_accepts_an_answer_that_covers_the_cost_outright():
    request = _payment(amount=5, available=1, produced=[("sh", 8), ("mine", 2)])
    assert request.accepts(DecisionResponse(("sh",))) is True  # 1 + 8 >= 5


def test_payment_takes_one_producer_at_a_time():
    """Two in one answer would open two production windows before either could be answered, so the
    second producer's question would overwrite the first's."""
    request = _payment(amount=5, available=1, produced=[("sh", 8), ("mine", 2)])

    assert request.accepts(DecisionResponse(("sh", "mine"))) is False


def test_payment_accepts_a_part_of_the_cost_while_a_producer_is_left():
    """Bowing some now and the rest when the payment comes back round is legal: the answer only has
    to leave the cost reachable, not meet it."""
    request = _payment(amount=5, available=1, produced=[("sh", 8), ("mine", 2)])

    assert request.accepts(DecisionResponse(("mine",))) is True  # 1 + 2 now, sh still to bow


def test_payment_rejects_an_answer_that_puts_the_cost_out_of_reach():
    """The other side of it: an answer with nothing left to bow afterwards would strand the payment
    with the board already changed, so it is refused before anything bows."""
    request = _payment(amount=5, available=1, produced=[("mine", 2)])

    assert request.accepts(DecisionResponse(("mine",))) is False  # 1 + 2 < 5, nothing else offered
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
    assert _discard(2).cancellable is False


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


def _grouped(minimum: int, maximum: int) -> ChooseAbilityTarget:
    return ChooseAbilityTarget(
        PlayerId.P1,
        _HAND,
        "src",
        minimum=minimum,
        maximum=maximum,
        limits=(OneGroup((("a", "b"), ("c",))),),
    )


def test_a_grouped_phrase_accepts_picks_from_one_group_only():
    request = _grouped(minimum=1, maximum=2)

    assert request.accepts(DecisionResponse(("a", "b"))) is True
    assert request.accepts(DecisionResponse(("c",))) is True
    assert request.accepts(DecisionResponse(("b", "c"))) is False


def test_a_grouped_phrase_offers_every_group_until_a_pick_settles_one():
    request = _grouped(minimum=1, maximum=2)

    assert request.selectable() == _HAND
    assert request.selectable(DecisionResponse(("a",))) == ("a", "b")
    assert request.selectable(DecisionResponse(("c",))) == ("c",)


def _capped(bound: int, minimum: int = 1) -> ChooseAbilityTarget:
    weights = (("a", 2), ("b", 3), ("c", 4))
    return ChooseAbilityTarget(
        PlayerId.P1, _HAND, "src", minimum=minimum, maximum=3, limits=(TotalAtMost(weights, bound),)
    )


def test_a_capped_phrase_accepts_a_set_within_the_total():
    request = _capped(bound=5)

    assert request.accepts(DecisionResponse(("a", "b"))) is True
    assert request.accepts(DecisionResponse(("b", "c"))) is False


def test_a_capped_phrase_drops_what_no_longer_fits_as_the_picks_mount():
    request = _capped(bound=5)

    assert request.selectable() == _HAND
    assert request.selectable(DecisionResponse(("a",))) == ("a", "b")
    assert request.selectable(DecisionResponse(("a", "b"))) == ("a", "b")


def test_a_candidate_outside_the_cap_is_never_offered_alone():
    # The weight of one card can break the total by itself. The engine drops such a card before it
    # offers anything; the request refuses it too, so the two agree.
    request = _capped(bound=3)

    assert request.selectable() == ("a", "b")
    assert request.accepts(DecisionResponse(("c",))) is False


def test_a_capped_phrase_counts_the_running_total_in_its_prompt():
    request = _capped(bound=5)

    assert request.prompt().endswith("(Selected 0/5)")
    assert request.prompt(DecisionResponse(("a",))).endswith("(Selected 2/5)")
    assert request.prompt(DecisionResponse(("a", "b"))).endswith("(Selected 5/5)")


def test_a_capped_phrase_says_nothing_once_the_answer_is_outside_its_weights():
    # "a" and "b" are weighted; "c" is not, as a Personality is not when the cap is over
    # attachments.
    request = ChooseAbilityTarget(
        PlayerId.P1,
        _HAND,
        "src",
        minimum=1,
        maximum=3,
        limits=(TotalAtMost((("a", 2), ("b", 3)), 4),),
    )

    assert request.prompt().endswith("(Selected 0/4)")
    assert request.prompt(DecisionResponse(("a",))).endswith("(Selected 2/4)")
    assert "Selected" not in request.prompt(DecisionResponse(("c",)))


def test_a_grouped_phrase_adds_nothing_to_its_prompt():
    request = _grouped(minimum=1, maximum=2)

    assert request.prompt(DecisionResponse(("a",))) == "Target 1 or 2 of the cards offered"


def _stacked() -> ChooseAbilityTarget:
    return ChooseAbilityTarget(
        PlayerId.P1,
        _HAND,
        "src",
        minimum=1,
        maximum=3,
        limits=(OneGroup((("a", "b"), ("c",))), TotalAtMost((("a", 2), ("b", 3), ("c", 1)), 4)),
    )


def test_stacked_limits_word_only_what_they_have_to_say():
    assert _stacked().prompt(DecisionResponse(("a",))).endswith("(Selected 2/4)")


def test_limits_stack_and_all_of_them_have_to_hold():
    request = _stacked()

    assert request.accepts(DecisionResponse(("a",))) is True
    assert request.accepts(DecisionResponse(("a", "b"))) is False  # one unit, but over the total
    assert request.accepts(DecisionResponse(("a", "c"))) is False  # under the total, two units


def test_a_grouped_limit_admits_only_what_one_part_can_seat():
    limit = OneGroup((("a", "b"), ("c",)))

    assert limit.admits(_HAND, 1) is True
    assert limit.admits(_HAND, 2) is True
    assert limit.admits(_HAND, 3) is False
    assert limit.admits(("b", "c"), 2) is False  # one from each part is not one part


def test_a_capped_limit_admits_what_its_cheapest_cards_can_carry():
    limit = TotalAtMost((("a", 2), ("b", 3), ("c", 4)), 5)

    assert limit.admits(_HAND, 2) is True  # a + b
    assert limit.admits(("b", "c"), 2) is False  # the cheapest pair left is already over
    assert limit.admits(_HAND, 3) is False


def test_a_question_with_no_legal_answer_is_not_answerable():
    # Three Personalities of Force 3 and a phrase taking two of them under a total of 5: every card
    # passes on its own, and no pair does.
    heavy = TotalAtMost((("a", 3), ("b", 3), ("c", 3)), 5)

    assert within_reach(_HAND, (heavy,)) == _HAND
    assert answerable(_HAND, 1, (heavy,)) is True
    assert answerable(_HAND, 2, (heavy,)) is False
    assert answerable(("a",), 2, ()) is False  # too few cards, limits or not


def test_an_ungrouped_choice_keeps_every_candidate_on_offer():
    request = _choose(minimum=0, maximum=2)

    assert request.selectable(DecisionResponse(("a",))) == _HAND


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


def test_the_target_prompt_names_the_condition_and_the_card():
    worded = ChooseAbilityTarget(
        PlayerId.P1, ("a",), "c", source_name="Banish all Shadows", targeting_message="your Monk"
    )
    unworded = ChooseAbilityTarget(PlayerId.P1, ("a",), "c", source_name="Millet Farm")

    assert worded.prompt() == "Banish all Shadows: target your Monk"
    assert unworded.prompt() == "Millet Farm: target a card"


def test_a_target_choice_of_several_takes_that_many_distinct_candidates():
    request = ChooseAbilityTarget(PlayerId.P1, ("a", "b", "c"), "spell", minimum=2, maximum=2)

    assert request.accepts(DecisionResponse(("a", "b")))
    assert not request.accepts(DecisionResponse(("a",)))
    assert not request.accepts(DecisionResponse(("a", "a")))
    assert not request.accepts(DecisionResponse(("a", "d")))


def test_payment_prompt_counts_down_as_producers_are_picked():
    request = _payment(amount=5, available=1, produced=(("a", 2), ("b", 2)))
    assert request.prompt() == "Pay 4 gold for Mine"
    assert request.prompt(DecisionResponse(("a",))) == "Pay 2 gold for Mine"
    assert request.prompt(DecisionResponse(("a", "b"))) == "Pay 0 gold for Mine"
    assert request.confirm_label == "Pay"


def test_choose_cards_wording_distinguishes_optional_from_required():
    assert _choose(minimum=0, maximum=2).prompt() == "Choose up to 2 cards"
    assert _choose(minimum=1, maximum=2).prompt() == "Choose 1 to 2 cards"


def test_choose_cards_asks_for_an_exact_count_as_one():
    """A range whose ends meet reads as a choice the effect is not offering. "Choose 1 to 1" asks
    the player to weigh how many to take when the answer is fixed."""
    assert _choose(minimum=1, maximum=1).prompt() == "Choose 1 card"
    assert _choose(minimum=2, maximum=2).prompt() == "Choose 2 cards"


@choice_resolver("test_prompted", prompt="Put a card on the bottom of your deck")
def _prompted(game, source_id, chosen, seat):
    return []


def test_a_registered_prompt_replaces_the_generic_wording():
    # The generic line names a count and nothing else, which tells a player how many cards to click
    # but never what the choice is for. The two are shown side by side because the fallback has to
    # survive: most choices register no prompt.
    prompted = ChooseCards(PlayerId.P1, _HAND, 0, 2, resolver="test_prompted")

    assert prompted.prompt() == "Put a card on the bottom of your deck"
    assert _choose(minimum=0, maximum=2).prompt() == "Choose up to 2 cards"


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


def test_a_cost_only_a_producers_own_grant_reaches_is_still_answerable():
    """Outlying Farms makes 2 and can raise itself to 4. The seat is asked for the grant in the
    window, as the Farm bows, so naming it here must not be refused for falling short."""
    request = _payment(amount=4, available=0, produced=[("of", 2)], grantable=[("of", 2)])

    assert request.accepts(DecisionResponse(("of",)))


def test_a_cost_beyond_every_ceiling_is_refused():
    request = _payment(amount=5, available=0, produced=[("of", 2)], grantable=[("of", 2)])

    assert not request.accepts(DecisionResponse(("of",)))


def test_a_payment_is_finishable_once_the_picks_reach_the_cost():
    request = _payment(amount=5, available=1, produced=[("sh", 2), ("mine", 2)])

    assert not request.covers_cost(DecisionResponse(("sh",)))  # 1 + 2 of 5
    assert request.covers_cost(DecisionResponse(("sh", "mine")))  # 1 + 4 of 5


def test_a_pick_may_reach_the_cost_through_its_own_grant():
    """The seat has not been asked for the grant yet, but it will be, in the window that pick opens
    as it bows. Refusing to let it finish would leave a legal purchase unbuyable."""
    request = _payment(amount=4, available=0, produced=[("of", 2)], grantable=[("of", 2)])

    assert request.covers_cost(DecisionResponse(("of",)))


def test_a_grant_belongs_to_the_producer_that_offers_it():
    """Only a producer being bowed is asked for its grant. Counting an unpicked one would light the
    finish button on a payment the seat has not actually covered."""
    request = _payment(
        amount=4, available=0, produced=[("of", 2), ("mine", 2)], grantable=[("of", 2)]
    )

    assert not request.covers_cost(DecisionResponse(("mine",)))  # 2 of 4; of's grant is not mine's
    assert request.covers_cost(DecisionResponse(("of",)))


def test_finishable_and_answerable_are_different_questions():
    """A seat picks its whole payment and the engine bows one producer per answer, so what a client
    may offer as finished and what the engine takes as one answer count different sets. Collapsing
    them is what makes a finish button light on the first of several picks."""
    request = _payment(amount=5, available=0, produced=[("sh", 3), ("mine", 2)])
    both = DecisionResponse(("sh", "mine"))
    one = DecisionResponse(("sh",))

    assert request.covers_cost(both) and not request.accepts(both)
    assert request.accepts(one) and not request.covers_cost(one)


def test_the_payment_prompt_quotes_what_a_producer_makes_now_not_what_it_could():
    """Clicking previews the bow, and the grant is not part of it. The seat has not been asked yet,
    and quoting the higher figure would promise gold it may decline."""
    request = _payment(amount=4, available=0, produced=[("of", 2)], grantable=[("of", 2)])

    assert request.prompt(DecisionResponse(("of",))) == "Pay 2 gold for Mine"


def test_discard_prompt_names_the_count():
    assert _discard(1).prompt() == "Discard 1 card"
    assert _discard(2).prompt() == "Discard 2 cards"
    assert _discard(1).confirm_label == "Discard"


def test_discard_prompt_names_the_holder_when_another_seat_chooses():
    assert _discard(1, seat=PlayerId.P2).prompt() == "Choose 1 card for P1 to discard"


def test_a_confirm_takes_yes_as_its_subjects_and_no_as_none():
    """The answer is the subjects or nothing, which is what an optional card choice already hands a
    resolver, so asking a question instead of offering a selection changes no resolver."""
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


def _distribution(count: int) -> ChooseDistribution:
    return ChooseDistribution(PlayerId.P1, _HAND, count=count, resolver="test_split", source_id="s")


def test_a_distribution_takes_a_candidate_once_per_creation_it_gets():
    # The point of the shape: two on "a" and one on "b" is three ids, not a set of two.
    assert _distribution(3).accepts(DecisionResponse(("a", "a", "b"))) is True


def test_a_distribution_may_heap_everything_on_one_candidate():
    """ "One or more" is a floor, not a spread: naming a single card is a legal division."""
    assert _distribution(3).accepts(DecisionResponse(("a", "a", "a"))) is True


def test_a_distribution_rejects_an_answer_that_places_the_wrong_number():
    # All of them are placed. The seat divides the creations and does not decline any.
    request = _distribution(3)
    assert request.accepts(DecisionResponse(("a", "b"))) is False
    assert request.accepts(DecisionResponse(("a", "a", "b", "b"))) is False
    assert request.accepts(DecisionResponse(())) is False


def test_a_distribution_rejects_a_candidate_it_never_offered():
    assert _distribution(2).accepts(DecisionResponse(("a", "z"))) is False


@choice_resolver("test_split", prompt="Attach them to one or more of your Personalities")
def _split(game, source_id, chosen, seat):
    return []


def test_a_distribution_prompt_counts_down_as_the_creations_are_placed():
    # A division is answered by clicking one card repeatedly, so the count left is the only thing
    # telling the player they are not finished.
    request = _distribution(3)

    assert request.prompt() == "Attach them to one or more of your Personalities (3 of 3 left)"
    assert request.prompt(DecisionResponse(("a", "a"))) == (
        "Attach them to one or more of your Personalities (1 of 3 left)"
    )


def test_a_distribution_with_no_registered_wording_still_says_what_it_wants():
    request = ChooseDistribution(
        PlayerId.P1, _HAND, count=2, resolver="unregistered", source_id="s"
    )

    assert request.prompt() == "Divide them among one or more cards (2 of 2 left)"


def test_a_choice_words_its_pick_as_its_resolver_registered_it_or_choose():
    CHOICE_PICKS["probe_pick"] = "Put on the bottom of your deck"
    try:
        registered = ChooseCards(PlayerId.P1, ("a",), 0, 1, "probe_pick")

        assert registered.pick_label == "Put on the bottom of your deck"
        assert _choose(0, 1).pick_label == "Choose"
    finally:
        CHOICE_PICKS.pop("probe_pick")


def test_an_arrangement_words_its_pick_by_the_end_of_the_deck():
    assert _arrange("a", to_bottom=True).pick_label == "Put on the bottom of your deck"
    assert _arrange("a").pick_label == "Put on top of your deck"


def test_a_declinable_choice_takes_nothing_or_exactly_its_count():
    request = ChooseCards(PlayerId.P1, _HAND, 2, 2, resolver="r", declinable=True)

    assert request.accepts(DecisionResponse(())) is True
    assert request.accepts(DecisionResponse(("a",))) is False
    assert request.accepts(DecisionResponse(("a", "b"))) is True


def _arrange(*candidates: str, to_bottom: bool = False) -> ArrangeCards:
    return ArrangeCards(PlayerId.P1, candidates, "r", "src", to_bottom)


def test_an_arrangement_is_every_candidate_exactly_once():
    assert _arrange("a", "b", "c").accepts(DecisionResponse(("c", "a", "b")))
    assert not _arrange("a", "b", "c").accepts(DecisionResponse(("a", "b")))
    assert not _arrange("a", "b", "c").accepts(DecisionResponse(("a", "b", "c", "d")))
    assert not _arrange("a", "b", "c").accepts(DecisionResponse(("a", "a", "b")))


def test_the_unchanged_arrangement_keeps_the_looked_at_order_at_either_end():
    """The last placed ends outermost, so keeping the top order places bottom-up and keeping the
    bottom order places top-down."""
    assert _arrange("top", "mid", "low").unchanged == ("low", "mid", "top")
    assert _arrange("top", "mid", "low", to_bottom=True).unchanged == ("top", "mid", "low")


def test_keeping_order_places_the_rest_as_looked_at_after_what_is_already_placed():
    assert _arrange("top", "mid", "low").keeping_order(("mid",)) == ("mid", "low", "top")
    assert _arrange("top", "mid", "low", to_bottom=True).keeping_order(("low",)) == (
        "low",
        "top",
        "mid",
    )


def test_an_arrangement_cannot_be_backed_out_of():
    assert not _arrange("a").cancellable


@pytest.mark.parametrize(
    ("choices", "accepted"),
    [((), False), (("a",), True), (("a", "b"), True), (("a", "a"), False), (("c",), False)],
)
def test_an_option_question_accepts_any_distinct_pick_within_its_bounds(choices, accepted):
    asked = ChooseOption(
        seat=PlayerId.P1,
        candidates=("a", "b"),
        question="Which?",
        resolver="probe",
        source_id="card",
        maximum=2,
    )

    assert asked.accepts(DecisionResponse(choices)) is accepted


def test_a_target_prompt_names_the_range_it_takes():
    one = ChooseAbilityTarget(PlayerId.P1, ("a",), "c", targeting_message="your Personality")
    several = ChooseAbilityTarget(
        PlayerId.P1, ("a", "b", "c"), "c", targeting_message="enemy Followers", minimum=1, maximum=2
    )
    exact = ChooseAbilityTarget(
        PlayerId.P1, ("a", "b"), "c", targeting_message="your Personalities", minimum=2, maximum=2
    )
    wide = ChooseAbilityTarget(
        PlayerId.P1, _HAND, "c", targeting_message="your Personalities", minimum=1, maximum=3
    )

    assert one.prompt() == "Target your Personality"
    assert several.prompt() == "Target 1 or 2 of enemy Followers"
    assert exact.prompt() == "Target 2 of your Personalities"
    assert wide.prompt() == "Target 1 to 3 of your Personalities"


def test_backing_out_of_a_later_target_phrase_returns_to_the_one_before_it():
    first = ChooseAbilityTarget(PlayerId.P1, ("a",), "c")
    second = ChooseAbilityTarget(PlayerId.P1, ("b",), "c", settled=(("a",),))

    assert first.reopens_on_cancel is False
    assert second.reopens_on_cancel is True

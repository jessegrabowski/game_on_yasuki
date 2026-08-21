from yasuki_gui.services.allocation import Allocation


def _allocation(total: int, *chosen: str) -> Allocation:
    allocation = Allocation(total)
    for card_id in chosen:
        allocation.toggle(card_id)
    return allocation


def test_one_card_takes_the_whole_lot():
    assert _allocation(3, "a").choices == ("a", "a", "a")


def test_two_cards_split_it_down_the_middle():
    allocation = _allocation(4, "a", "b")

    assert [allocation.amount(card) for card in "ab"] == [2, 2]


def test_an_uneven_split_hands_the_remainder_to_the_cards_picked_first():
    allocation = _allocation(5, "a", "b", "c")

    assert [allocation.amount(card) for card in "abc"] == [2, 2, 1]


def test_the_answer_names_a_card_once_per_creation_it_carries():
    # The shape the engine reads: a division rather than a set, so two on "a" is "a" twice.
    allocation = _allocation(3, "a", "b")

    assert allocation.choices == ("a", "a", "b")


def test_choosing_another_card_re_splits_rather_than_keeping_the_old_shares():
    """Every selection change starts the division over, so the split a player sees is always the
    even one they can then adjust from."""
    allocation = _allocation(4, "a")
    assert allocation.amount("a") == 4

    allocation.toggle("b")

    assert [allocation.amount(card) for card in "ab"] == [2, 2]


def test_dropping_a_card_gives_its_share_back_to_the_rest():
    allocation = _allocation(4, "a", "b")

    allocation.toggle("b")

    assert allocation.amount("a") == 4
    assert allocation.chosen == ("a",)


def test_no_more_cards_may_be_chosen_than_there_are_creations():
    # A card chosen beyond that could only be given nothing, which is not a choice at all.
    allocation = _allocation(2, "a", "b")

    allocation.toggle("c")

    assert allocation.chosen == ("a", "b")


def test_an_arrow_moves_one_across_without_changing_the_total():
    allocation = _allocation(4, "a", "b")

    allocation.increase("a")

    assert [allocation.amount(card) for card in "ab"] == [3, 1]
    assert len(allocation.choices) == 4


def test_a_card_may_not_be_emptied_by_an_arrow():
    """Carrying nothing is what being unchosen means, so the last one cannot be taken away — the
    player deselects the card instead."""
    allocation = _allocation(2, "a", "b")

    allocation.decrease("a")

    assert [allocation.amount(card) for card in "ab"] == [1, 1]
    assert allocation.may_decrease("a") is False


def test_an_increase_takes_from_the_fullest_neighbour():
    # Taking from the fullest keeps the division as even as the player left it. "b" is deliberately
    # the fullest but not the first of "c"'s neighbours, so taking from whichever came first would
    # fail this.
    allocation = _allocation(7, "a", "b", "c")  # 3, 2, 2
    allocation.decrease("a")  # 2, 3, 2

    allocation.increase("c")

    assert [allocation.amount(card) for card in "abc"] == [2, 2, 3]


def test_a_decrease_gives_to_the_emptiest_neighbour():
    allocation = _allocation(5, "a", "b", "c")  # 2, 2, 1

    allocation.decrease("a")

    assert [allocation.amount(card) for card in "abc"] == [1, 2, 2]


def test_a_single_card_has_nothing_to_trade_with():
    """The arrows are there but do nothing: with one card chosen the division is already settled."""
    allocation = _allocation(3, "a")

    assert allocation.may_increase("a") is False
    assert allocation.may_decrease("a") is False


def test_an_unchosen_card_carries_nothing_and_trades_nothing():
    allocation = _allocation(3, "a")

    assert allocation.amount("z") == 0
    assert allocation.may_increase("z") is False
    assert allocation.may_decrease("z") is False


def test_nothing_chosen_is_an_empty_answer():
    assert Allocation(3).choices == ()

from app.gui.ui.deck_builder.deck_data import DeckState


def test_deck_state_initialization():
    state = DeckState()
    assert state.cards == {}


def test_deck_state_add_card():
    state = DeckState()
    new_state = state.add_card("card1", 1)

    assert state.cards == {}
    assert new_state.cards == {"card1": [(1, 1)]}


def test_deck_state_add_same_card_same_print():
    state = DeckState()
    state = state.add_card("card1", 1)
    state = state.add_card("card1", 1)

    assert state.cards == {"card1": [(1, 2)]}


def test_deck_state_add_same_card_different_print():
    state = DeckState()
    state = state.add_card("card1", 1)
    state = state.add_card("card1", 2)

    assert state.cards == {"card1": [(1, 1), (2, 1)]}


def test_deck_state_remove_card_any_print():
    state = DeckState(cards={"card1": [(1, 2)]})
    new_state = state.remove_card("card1")

    assert new_state.cards == {"card1": [(1, 1)]}


def test_deck_state_remove_card_last_copy():
    state = DeckState(cards={"card1": [(1, 1)]})
    new_state = state.remove_card("card1")

    assert new_state.cards == {}


def test_deck_state_remove_card_specific_print():
    state = DeckState(cards={"card1": [(1, 2), (2, 1)]})
    new_state = state.remove_card("card1", print_id=2)

    assert new_state.cards == {"card1": [(1, 2)]}


def test_deck_state_remove_nonexistent_card():
    state = DeckState()
    new_state = state.remove_card("card1")

    assert new_state.cards == {}


def test_deck_state_clear():
    state = DeckState(cards={"card1": [(1, 2)], "card2": [(3, 1)]})
    new_state = state.clear()

    assert new_state.cards == {}


def test_deck_state_get_card_count():
    cards_by_id = {
        "card1": {"id": "card1", "side": "FATE"},
        "card2": {"id": "card2", "side": "FATE"},
        "card3": {"id": "card3", "side": "DYNASTY"},
        "card4": {"id": "card4", "side": "STRONGHOLD"},
    }

    state = DeckState(
        cards={
            "card1": [(1, 2)],
            "card2": [(1, 3)],
            "card3": [(1, 4)],
            "card4": [(1, 1)],
        }
    )

    assert state.get_card_count("FATE", cards_by_id) == 5
    assert state.get_card_count("DYNASTY", cards_by_id) == 4
    assert state.get_card_count("SETUP", cards_by_id) == 1


def test_deck_state_immutability():
    state1 = DeckState()
    state2 = state1.add_card("card1", 1)

    assert state1 is not state2
    assert state1.cards != state2.cards

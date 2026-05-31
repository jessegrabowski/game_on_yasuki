from unittest.mock import patch

from yasuki_core.card_art import CustomPrint, custom_print_id
from yasuki_gui.ui.deck_builder.deck_data import DeckState


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
        "card1": {"card_id": "card1", "decks": ["Fate"]},
        "card2": {"card_id": "card2", "decks": ["Fate"]},
        "card3": {"card_id": "card3", "decks": ["Dynasty"]},
        "card4": {"card_id": "card4", "decks": ["Pre-Game"]},
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


def test_repository_registers_and_surfaces_custom_print():
    cards = [
        {"card_id": "collision", "name": "A Collision of Wills", "types": ["Strategy"]},
        {
            "card_id": "ikumu",
            "name": "Togashi Ikumu",
            "extended_title": "Togashi Ikumu",
            "types": ["Personality"],
        },
    ]
    with (
        patch("yasuki_gui.ui.deck_builder.deck_data.load_cards_from_db", return_value=cards),
        patch("yasuki_gui.ui.deck_builder.deck_data.get_prints_by_card_id", return_value=[]),
    ):
        from yasuki_gui.ui.deck_builder.deck_data import DeckBuilderRepository

        repo = DeckBuilderRepository()
        recipe = CustomPrint("collision", 100, "ikumu", 200)
        pid = repo.register_custom_print(recipe)

        assert pid == custom_print_id(recipe)
        assert repo.get_custom_print(pid) == recipe

        prints = repo.get_prints("collision")
        assert len(prints) == 1
        assert prints[0]["is_custom"] is True
        assert prints[0]["print_id"] == pid
        assert "Togashi Ikumu" in prints[0]["set_name"]

        # The custom surfaces only under its recipient, never under the donor card.
        assert repo.get_prints("ikumu") == []

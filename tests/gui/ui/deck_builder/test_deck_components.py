import tkinter as tk
from unittest.mock import Mock

import pytest

from app.gui.ui.deck_builder.deck_components import (
    FilteredCardList,
    DeckCardList,
    extract_card_id,
    extract_print_and_card_id,
)
from app.gui.ui.deck_builder.deck_data import DeckState


@pytest.fixture
def root():
    root = tk.Tk()
    yield root
    root.destroy()


@pytest.fixture
def mock_repository():
    repo = Mock()
    repo.filter_cards = Mock(
        return_value=[
            {"id": "card1", "name": "Test Card 1"},
            {"id": "card2", "name": "Test Card 2"},
        ]
    )
    repo.get_card = Mock(
        side_effect=lambda card_id: {
            "card1": {"id": "card1", "name": "Test Card 1", "side": "FATE"},
            "card2": {"id": "card2", "name": "Test Card 2", "side": "DYNASTY"},
        }.get(card_id)
    )
    repo.get_prints = Mock(return_value=[{"print_id": 1, "set_name": "Test Set"}])
    return repo


def test_extract_card_id():
    assert extract_card_id("Card Name ⟨card123⟩") == "card123"
    assert extract_card_id("Complex Name - Experienced ⟨complex_id⟩") == "complex_id"
    assert extract_card_id("No brackets") is None


def test_extract_print_and_card_id():
    result = extract_print_and_card_id("Card Name x2 ⟨42:card123⟩")
    assert result == (42, "card123")

    result = extract_print_and_card_id("Another Card ⟨1:other_id⟩")
    assert result == (1, "other_id")

    assert extract_print_and_card_id("No brackets") is None


def test_filtered_card_list_initialization(root, mock_repository):
    card_list = FilteredCardList(root, mock_repository)
    assert card_list._repository is mock_repository
    assert card_list._filter_query == ""


def test_filtered_card_list_set_filter(root, mock_repository):
    card_list = FilteredCardList(root, mock_repository)
    card_list.set_filter("test query")

    assert card_list._filter_query == "test query"
    mock_repository.filter_cards.assert_called_with("test query", None)


def test_filtered_card_list_set_filter_options(root, mock_repository):
    from app.gui.ui.deck_builder.filter_dialog import FilterOptions

    card_list = FilteredCardList(root, mock_repository)

    filter_opts = FilterOptions()
    filter_opts.add_filter("legality", ("Ivory Edition", ["legal"]))
    card_list.set_filter_options(filter_opts)

    assert card_list._filter_options == filter_opts
    mock_repository.filter_cards.assert_called_with("", filter_opts)


def test_filtered_card_list_refresh(root, mock_repository):
    card_list = FilteredCardList(root, mock_repository)
    card_list.refresh()

    mock_repository.filter_cards.assert_called_once()
    assert card_list.listbox.size() == 2


def test_filtered_card_list_get_selected_card_id(root, mock_repository):
    card_list = FilteredCardList(root, mock_repository)
    card_list.refresh()

    card_list.listbox.selection_set(0)
    card_id = card_list.get_selected_card_id()
    assert card_id == "card1"


def test_deck_card_list_initialization(root, mock_repository):
    deck_list = DeckCardList(root, mock_repository, "FATE")
    assert deck_list._repository is mock_repository
    assert deck_list._side == "FATE"


def test_deck_card_list_refresh_fate(root, mock_repository):
    # Update mock to include type information
    mock_repository.get_card = Mock(
        side_effect=lambda card_id: {
            "card1": {"id": "card1", "name": "Test Card 1", "side": "FATE", "type": "Strategy"},
        }.get(card_id)
    )

    deck_list = DeckCardList(root, mock_repository, "FATE")
    deck_state = DeckState(cards={"card1": [(1, 2)]})

    deck_list.refresh(deck_state)

    # Should show 2 lines: type header + card
    assert deck_list.listbox.size() == 2

    # Check type header
    type_header = deck_list.listbox.get(0)
    assert "2x Strategies" in type_header

    # Check card entry (indented)
    item_text = deck_list.listbox.get(1)
    assert "Test Card 1" in item_text
    assert "2x" in item_text
    assert "[Test Set]" in item_text
    assert item_text.startswith("    ")  # Should be indented


def test_deck_card_list_refresh_dynasty(root, mock_repository):
    # Update mock to include type information
    mock_repository.get_card = Mock(
        side_effect=lambda card_id: {
            "card2": {
                "id": "card2",
                "name": "Test Card 2",
                "side": "DYNASTY",
                "type": "Personality",
            },
        }.get(card_id)
    )

    deck_list = DeckCardList(root, mock_repository, "DYNASTY")
    deck_state = DeckState(cards={"card2": [(1, 3)]})

    deck_list.refresh(deck_state)

    # Should show 2 lines: type header + card
    assert deck_list.listbox.size() == 2

    # Check type header
    type_header = deck_list.listbox.get(0)
    assert "3x Personalities" in type_header

    # Check card entry
    item_text = deck_list.listbox.get(1)
    assert "Test Card 2" in item_text
    assert "3x" in item_text


def test_deck_card_list_filters_by_side(root, mock_repository):
    deck_list = DeckCardList(root, mock_repository, "FATE")
    deck_state = DeckState(
        cards={
            "card1": [(1, 2)],
            "card2": [(1, 1)],
        }
    )

    deck_list.refresh(deck_state)

    # Should only show card1 (FATE), not card2 (DYNASTY)
    # 2 lines: type header + card1
    assert deck_list.listbox.size() == 2


def test_deck_card_list_get_selected_ids(root, mock_repository):
    deck_list = DeckCardList(root, mock_repository, "FATE")
    deck_state = DeckState(cards={"card1": [(42, 2)]})

    mock_repository.get_prints = Mock(return_value=[{"print_id": 42, "set_name": "Test"}])
    deck_list.refresh(deck_state)

    # Select the card entry (index 1, after type header at index 0)
    deck_list.listbox.selection_set(1)
    result = deck_list.get_selected_ids()
    assert result == (42, "card1")


def test_deck_card_list_setup_side(root, mock_repository):
    deck_list = DeckCardList(root, mock_repository, "SETUP")

    # Add a stronghold card (which is neither FATE nor DYNASTY)
    mock_repository.get_card = Mock(
        side_effect=lambda card_id: {
            "stronghold1": {
                "id": "stronghold1",
                "name": "Test Stronghold",
                "side": "STRONGHOLD",
                "type": "Stronghold",
            },
            "card1": {"id": "card1", "name": "Test Card 1", "side": "FATE", "type": "Strategy"},
        }.get(card_id)
    )

    deck_state = DeckState(
        cards={
            "stronghold1": [(1, 1)],
            "card1": [(1, 1)],
        }
    )

    deck_list.refresh(deck_state)

    # Should show 2 lines: type header + stronghold (not the FATE card)
    assert deck_list.listbox.size() == 2
    type_header = deck_list.listbox.get(0)
    assert "Strongholds" in type_header
    item_text = deck_list.listbox.get(1)
    assert "Stronghold" in item_text


def test_deck_card_list_multiple_prints_hierarchical(root, mock_repository):
    # Add type info to mock
    mock_repository.get_card = Mock(
        side_effect=lambda card_id: {
            "card1": {"id": "card1", "name": "Test Card 1", "side": "FATE", "type": "Strategy"},
        }.get(card_id)
    )

    deck_list = DeckCardList(root, mock_repository, "FATE")

    # Mock get_prints to return multiple sets
    mock_repository.get_prints = Mock(
        return_value=[
            {"print_id": 1, "set_name": "Imperial Edition"},
            {"print_id": 2, "set_name": "Ivory Edition"},
            {"print_id": 3, "set_name": "Twenty Festivals"},
        ]
    )

    deck_state = DeckState(
        cards={
            "card1": [(1, 1), (2, 1), (3, 1)],
        }
    )

    deck_list.refresh(deck_state)

    # Should show 5 lines: type header + main entry + 3 sub-entries
    assert deck_list.listbox.size() == 5

    # Check type header
    type_header = deck_list.listbox.get(0)
    assert "3x Strategies" in type_header

    # Check main card entry (indented under type)
    main_entry = deck_list.listbox.get(1)
    assert "3x Test Card 1" in main_entry
    assert "[" not in main_entry  # No set name on main entry
    assert main_entry.startswith("    ")  # Indented under type

    # Check sub-entries (double indented)
    sub1 = deck_list.listbox.get(2)
    assert "1x" in sub1
    assert "Imperial Edition" in sub1
    assert sub1.startswith("        ")  # Double indented

    sub2 = deck_list.listbox.get(3)
    assert "1x" in sub2
    assert "Ivory Edition" in sub2

    sub3 = deck_list.listbox.get(4)
    assert "1x" in sub3
    assert "Twenty Festivals" in sub3


def test_deck_card_list_single_print_one_line(root, mock_repository):
    # Add type info to mock
    mock_repository.get_card = Mock(
        side_effect=lambda card_id: {
            "card1": {"id": "card1", "name": "Test Card 1", "side": "FATE", "type": "Strategy"},
        }.get(card_id)
    )

    deck_list = DeckCardList(root, mock_repository, "FATE")

    deck_state = DeckState(
        cards={
            "card1": [(1, 3)],
        }
    )

    deck_list.refresh(deck_state)

    # Should show 2 lines: type header + card
    assert deck_list.listbox.size() == 2

    # Check type header
    type_header = deck_list.listbox.get(0)
    assert "3x Strategies" in type_header

    # Check card entry: count first, set name in brackets, indented
    entry = deck_list.listbox.get(1)
    assert "3x Test Card 1 [Test Set]" in entry
    assert "⟨" not in entry  # No angle brackets
    assert entry.startswith("    ")  # Indented under type


def test_deck_card_list_multiple_types_grouped(root, mock_repository):
    # Mock cards with different types
    mock_repository.get_card = Mock(
        side_effect=lambda card_id: {
            "strategy1": {"id": "strategy1", "name": "Ambush", "side": "FATE", "type": "Strategy"},
            "strategy2": {
                "id": "strategy2",
                "name": "Uncertainty",
                "side": "FATE",
                "type": "Strategy",
            },
            "item1": {"id": "item1", "name": "Naginata", "side": "FATE", "type": "Item"},
        }.get(card_id)
    )

    deck_list = DeckCardList(root, mock_repository, "FATE")

    deck_state = DeckState(
        cards={
            "strategy1": [(1, 3)],
            "strategy2": [(1, 2)],
            "item1": [(1, 2)],
        }
    )

    deck_list.refresh(deck_state)

    # Should show: Item header + item, Strategy header + 2 strategies (alphabetical)
    # 5 lines total
    assert deck_list.listbox.size() == 5

    # Check first type (Items - alphabetically first)
    items_header = deck_list.listbox.get(0)
    assert "2x Items" in items_header

    item_entry = deck_list.listbox.get(1)
    assert "2x Naginata" in item_entry

    # Check second type (Strategies)
    strategies_header = deck_list.listbox.get(2)
    assert "5x Strategies" in strategies_header

    # Check strategies are sorted by name
    strategy1_entry = deck_list.listbox.get(3)
    assert "3x Ambush" in strategy1_entry

    strategy2_entry = deck_list.listbox.get(4)
    assert "2x Uncertainty" in strategy2_entry

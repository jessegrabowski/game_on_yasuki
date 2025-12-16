import tkinter as tk
from unittest.mock import Mock, patch

import pytest

from app.gui.ui.deck_builder.deck_builder import DeckBuilderWindow, open_deck_builder


@pytest.fixture
def root():
    root = tk.Tk()
    yield root
    root.destroy()


@pytest.fixture
def mock_repository():
    with patch("app.gui.ui.deck_builder.deck_builder.DeckBuilderRepository") as mock:
        repo_instance = Mock()
        repo_instance.all_cards = [{"id": "card1", "name": "Test Card"}]
        repo_instance.filter_cards = Mock(return_value=[])
        repo_instance.get_card = Mock(return_value=None)
        repo_instance.get_prints = Mock(return_value=[])
        repo_instance.cards_by_id = {}
        mock.return_value = repo_instance
        yield mock


class TestDeckBuilderWindow:
    def test_initialization(self, root, mock_repository):
        window = DeckBuilderWindow(root)

        assert window.win is not None
        assert window.win.title() == "Deck Builder"
        assert window._repository is not None
        assert window._deck_state is not None

        window.win.destroy()

    def test_has_three_columns(self, root, mock_repository):
        window = DeckBuilderWindow(root)

        assert window.card_list is not None
        assert window.fate_list is not None
        assert window.dynasty_list is not None
        assert window.preview_controller is not None

        window.win.destroy()

    def test_search_functionality(self, root, mock_repository):
        window = DeckBuilderWindow(root)

        window.search_var.set("test query")
        window._on_search_changed()

        window._repository.filter_cards.assert_called()

        window.win.destroy()

    def test_close_window(self, root, mock_repository):
        on_close_callback = Mock()
        window = DeckBuilderWindow(root, on_close=on_close_callback)

        window._close()

        on_close_callback.assert_called_once()

    def test_clear_deck(self, root, mock_repository):
        window = DeckBuilderWindow(root)

        window._deck_state = window._deck_state.add_card("card1", 1)
        window._clear_deck()

        assert len(window._deck_state.cards) == 0

        window.win.destroy()

    def test_add_selected_no_card(self, root, mock_repository):
        window = DeckBuilderWindow(root)
        window.card_list.get_selected_card_id = Mock(return_value=None)

        window._add_selected()

        assert len(window._deck_state.cards) == 0

        window.win.destroy()

    def test_add_selected_with_card(self, root, mock_repository):
        window = DeckBuilderWindow(root)
        window.card_list.get_selected_card_id = Mock(return_value="card1")
        window._repository.get_prints = Mock(return_value=[{"print_id": 1}])

        window._add_selected()

        assert "card1" in window._deck_state.cards

        window.win.destroy()

    def test_clear_filters(self, root, mock_repository):
        window = DeckBuilderWindow(root)

        # Set some filters and search text
        window.search_var.set("test search")
        from app.gui.ui.deck_builder.filter_dialog import FilterOptions

        window._filter_options = FilterOptions()
        window._filter_options.add_filter("clan", "Crab")

        # Clear filters
        window._clear_filters()

        # Verify everything is cleared
        assert window.search_var.get() == ""
        assert not window._filter_options.has_filters()

        window.win.destroy()


def test_open_deck_builder(root, mock_repository):
    window = open_deck_builder(root)

    assert isinstance(window, DeckBuilderWindow)
    assert window.win is not None

    window.win.destroy()

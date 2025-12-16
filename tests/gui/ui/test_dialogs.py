import tkinter as tk
from unittest.mock import Mock

import pytest

from app.gui.ui.dialogs import Dialogs
from app.gui.ui.images import ImageProvider


@pytest.fixture
def root():
    root = tk.Tk()
    yield root
    root.destroy()


@pytest.fixture
def image_provider(root):
    return ImageProvider(root)


@pytest.fixture
def dialogs(root, image_provider):
    return Dialogs(root, image_provider)


class TestDialogs:
    def test_initialization(self, root, image_provider):
        dialogs = Dialogs(root, image_provider)

        assert dialogs.toplevel is root
        assert dialogs.images is image_provider

    def test_deck_inspect(self, dialogs, root):
        mock_deck = Mock()
        mock_deck.cards = []

        mock_deck_visual = Mock()
        mock_deck_visual.label = "Test Deck"
        mock_deck_visual.deck = mock_deck

        dialogs.deck_inspect(mock_deck_visual)

    def test_deck_search_empty(self, dialogs):
        mock_deck = Mock()
        mock_deck.cards = []

        mock_deck_visual = Mock()
        mock_deck_visual.label = "Test Deck"
        mock_deck_visual.deck = mock_deck

        draw_cb = Mock()
        dialogs.deck_search(mock_deck_visual, draw_cb)

    def test_deck_search_with_cards(self, dialogs):
        card1 = Mock()
        card1.name = "Card 1"
        card1.bowed = False
        card1.face_up = True
        card1.inverted = False
        card1.image_front = None

        mock_deck = Mock()
        mock_deck.cards = [card1]

        mock_deck_visual = Mock()
        mock_deck_visual.label = "Test Deck"
        mock_deck_visual.deck = mock_deck

        draw_cb = Mock()
        dialogs.deck_search(mock_deck_visual, draw_cb, n=1)

    def test_deck_reveal_top(self, dialogs):
        mock_deck_visual = Mock()
        mock_deck_visual.label = "Test Deck"

        dialogs.deck_reveal_top(mock_deck_visual)

    def test_preferences(self, dialogs):
        on_apply = Mock()

        dialogs.preferences("TestPlayer", None, on_apply)

import tkinter as tk
from unittest.mock import Mock

import pytest

from yasuki_gui.ui.dialogs import Dialogs
from yasuki_gui.ui.images import ImageProvider


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
        dialogs.deck_inspect([], "Test Deck")

    def test_deck_search_empty(self, dialogs):
        draw_cb = Mock()
        dialogs.deck_search([], "Test Deck", draw_cb)

    def test_deck_search_with_cards(self, dialogs):
        card1 = Mock()
        card1.name = "Card 1"
        card1.bowed = False
        card1.face_up = True
        card1.inverted = False
        card1.image_front = None

        draw_cb = Mock()
        dialogs.deck_search([card1], "Test Deck", draw_cb, n=1)

    def test_deck_reveal_top(self, dialogs):
        mock_deck_visual = Mock()
        mock_deck_visual.label = "Test Deck"

        dialogs.deck_reveal_top(mock_deck_visual)

    def test_discard_dialog_enables_submit_at_the_exact_count(self, dialogs):
        card = Mock()
        card.id = "h0"
        card.name = "Alpha"
        submitted = []
        dialogs.discard_to_hand_size([card], 1, submitted.append)

        win = [w for w in dialogs.toplevel.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        buttons = _all_buttons(win)
        card_btn = next(b for b in buttons if b.cget("text") == "Alpha")
        submit_btn = next(b for b in buttons if b.cget("text") == "Discard")

        assert str(submit_btn.cget("state")) == "disabled"
        card_btn.invoke()  # selecting the one required card enables submit
        assert str(submit_btn.cget("state")) == "normal"
        submit_btn.invoke()
        assert submitted == [("h0",)]

    def test_discard_dialog_caps_selection_and_allows_deselect(self, dialogs):
        cards = []
        for cid, name in (("h0", "Alpha"), ("h1", "Beta")):
            card = Mock()
            card.id = cid
            card.name = name
            cards.append(card)
        dialogs.discard_to_hand_size(cards, 1, lambda ids: None)

        win = [w for w in dialogs.toplevel.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        buttons = _all_buttons(win)
        alpha = next(b for b in buttons if b.cget("text") == "Alpha")
        beta = next(b for b in buttons if b.cget("text") == "Beta")
        submit = next(b for b in buttons if b.cget("text") == "Discard")

        alpha.invoke()
        assert str(submit.cget("state")) == "normal"
        beta.invoke()  # already at the cap of one, so this selection is ignored
        assert str(submit.cget("state")) == "normal"
        alpha.invoke()  # deselecting drops back below the count
        assert str(submit.cget("state")) == "disabled"

    def test_preferences(self, dialogs):
        on_apply = Mock()

        dialogs.preferences("TestPlayer", None, on_apply)


def _all_buttons(widget: tk.Misc) -> list[tk.Button]:
    found = [widget] if isinstance(widget, tk.Button) else []
    for child in widget.winfo_children():
        found.extend(_all_buttons(child))
    return found

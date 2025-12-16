import tkinter as tk
from unittest.mock import Mock

import pytest

from app.gui.ui.deck_builder.components import (
    CardStatsPanel,
    PrintSelector,
    ScrollableListBox,
)


@pytest.fixture
def root():
    root = tk.Tk()
    yield root
    root.destroy()


class TestScrollableListBox:
    def test_initialization(self, root):
        listbox = ScrollableListBox(root)
        assert listbox.listbox is not None
        assert listbox.frame is not None

    def test_insert_and_clear(self, root):
        listbox = ScrollableListBox(root)
        listbox.insert(0, "Item 1")
        listbox.insert(1, "Item 2")
        assert listbox.listbox.size() == 2

        listbox.clear()
        assert listbox.listbox.size() == 0

    def test_get_selection(self, root):
        listbox = ScrollableListBox(root)
        listbox.insert(0, "Item 1")
        listbox.insert(1, "Item 2")
        listbox.listbox.selection_set(0)
        assert 0 in listbox.get_selection()


class TestCardStatsPanel:
    def test_initialization(self, root):
        panel = CardStatsPanel(root)
        assert panel.frame is not None
        assert panel.name_label is not None
        assert panel.type_label is not None
        assert panel.clan_label is not None
        assert len(panel.stats) == 9  # 9 numeric stats

    def test_update_stats_personality(self, root):
        panel = CardStatsPanel(root)
        card = {
            "name": "Akodo Toturi",
            "type": "Personality",
            "clan": "Lion",
            "gold_cost": 15,
            "force": 5,
            "chi": 3,
            "personal_honor": 2,
        }
        panel.update_stats(card)

        # Check string data (row 1)
        assert panel.name_label.cget("text") == "Akodo Toturi"
        assert panel.type_label.cget("text") == "Personality"
        assert panel.clan_label.cget("text") == "Lion"

        # Check numeric data (row 2)
        assert panel.stats["force"][1].cget("text") == "5"
        assert panel.stats["chi"][1].cget("text") == "3"
        assert panel.stats["personal_honor"][1].cget("text") == "2"
        assert panel.stats["gold_cost"][1].cget("text") == "15"

    def test_update_stats_holding(self, root):
        panel = CardStatsPanel(root)
        card = {
            "name": "Gold Mine",
            "type": "Holding",
            "clan": "Crab",
            "gold_cost": 3,
            "gold_production": 2,
        }
        panel.update_stats(card)

        assert panel.name_label.cget("text") == "Gold Mine"
        assert panel.type_label.cget("text") == "Holding"
        assert panel.stats["gold_production"][1].cget("text") == "2"
        assert panel.stats["gold_cost"][1].cget("text") == "3"

    def test_update_stats_stronghold(self, root):
        panel = CardStatsPanel(root)
        card = {
            "name": "Shiro Kitsuki",
            "type": "Stronghold",
            "clan": "Dragon",
            "starting_honor": 10,
            "gold_production": 5,
            "province_strength": 8,
        }
        panel.update_stats(card)

        assert panel.name_label.cget("text") == "Shiro Kitsuki"
        assert panel.stats["starting_honor"][1].cget("text") == "10"
        assert panel.stats["gold_production"][1].cget("text") == "5"
        assert panel.stats["province_strength"][1].cget("text") == "8"

    def test_clear(self, root):
        panel = CardStatsPanel(root)
        card = {
            "name": "Test Card",
            "type": "Personality",
            "clan": "Lion",
            "force": 3,
        }
        panel.update_stats(card)

        panel.clear()

        assert panel.name_label.cget("text") == "—"
        assert panel.type_label.cget("text") == "—"
        assert panel.clan_label.cget("text") == "—"

    def test_hide_unused_stats(self, root):
        panel = CardStatsPanel(root)
        card = {
            "name": "Simple Card",
            "type": "Event",
            "clan": "Crane",
            "gold_cost": 2,
            # No force, chi, etc.
        }
        panel.update_stats(card)

        # Stats with None values should be hidden (pack_forget)
        # Only gold_cost should be visible
        assert panel.stats["gold_cost"][1].cget("text") == "2"


class TestPrintSelector:
    def test_initialization(self, root):
        on_prev = Mock()
        on_next = Mock()
        selector = PrintSelector(root, on_prev, on_next)

        assert selector.prev_btn.cget("state") == "disabled"
        assert selector.next_btn.cget("state") == "disabled"
        assert selector.info_lbl.cget("text") == ""

    def test_update_single_print(self, root):
        on_prev = Mock()
        on_next = Mock()
        selector = PrintSelector(root, on_prev, on_next)

        selector.update("Test Set", 0, 1)

        assert selector.info_lbl.cget("text") == "Test Set"
        assert selector.prev_btn.cget("state") == "disabled"
        assert selector.next_btn.cget("state") == "disabled"

    def test_update_multiple_prints(self, root):
        on_prev = Mock()
        on_next = Mock()
        selector = PrintSelector(root, on_prev, on_next)

        selector.update("Test Set", 0, 3)

        assert selector.info_lbl.cget("text") == "Test Set (1/3)"
        assert selector.prev_btn.cget("state") == "normal"
        assert selector.next_btn.cget("state") == "normal"

    def test_update_navigation_index(self, root):
        on_prev = Mock()
        on_next = Mock()
        selector = PrintSelector(root, on_prev, on_next)

        selector.update("Another Set", 1, 3)
        assert selector.info_lbl.cget("text") == "Another Set (2/3)"

    def test_clear(self, root):
        on_prev = Mock()
        on_next = Mock()
        selector = PrintSelector(root, on_prev, on_next)

        selector.update("Test Set", 0, 2)
        selector.clear()

        assert selector.info_lbl.cget("text") == ""
        assert selector.prev_btn.cget("state") == "disabled"
        assert selector.next_btn.cget("state") == "disabled"

    def test_button_callbacks(self, root):
        on_prev = Mock()
        on_next = Mock()
        selector = PrintSelector(root, on_prev, on_next)

        selector.update("Test Set", 0, 2)

        selector.prev_btn.invoke()
        on_prev.assert_called_once()

        selector.next_btn.invoke()
        on_next.assert_called_once()

import tkinter as tk
from unittest.mock import Mock

import pytest

from app.gui.ui.deck_builder.card_preview import (
    format_card_display_name,
    CardPreviewController,
)


def test_format_card_display_name_simple():
    card = {"name": "Test Card", "id": "test_card"}
    result = format_card_display_name(card)
    assert result == "Test Card"


def test_format_card_display_name_with_set():
    card = {"name": "Test Card", "id": "test_card"}
    result = format_card_display_name(card, "Test Set")
    assert result == "Test Card [Test Set]"


def test_format_card_display_name_experienced():
    card = {"name": "Daigotsu", "id": "daigotsu_exp"}
    result = format_card_display_name(card)
    assert "Experienced" in result


def test_format_card_display_name_experienced_level():
    card = {"name": "Daigotsu", "id": "daigotsu_exp2"}
    result = format_card_display_name(card)
    assert "Experienced 2" in result


@pytest.fixture
def root():
    root = tk.Tk()
    yield root
    root.destroy()


@pytest.fixture
def preview_components(root):
    image_label = tk.Label(root)

    stats_panel = Mock()
    stats_panel.update_stats = Mock()
    stats_panel.clear = Mock()

    text_widget = tk.Text(root)
    flavor_widget = tk.Text(root)

    print_selector = Mock()
    print_selector.update = Mock()
    print_selector.clear = Mock()

    return image_label, stats_panel, text_widget, flavor_widget, print_selector


def test_preview_controller_load_card(root, preview_components):
    mock_repo = Mock()
    mock_repo.get_prints.return_value = [
        {"print_id": 1, "set_name": "Test Set", "image_path": None}
    ]
    mock_repo.get_card.return_value = {
        "id": "card1",
        "name": "Test Card",
        "type": "personality",
        "side": "FATE",
        "text": "Test text",
    }

    image_label, stats_panel, text_widget, flavor_widget, print_selector = preview_components
    controller = CardPreviewController(
        image_label, stats_panel, text_widget, flavor_widget, print_selector, root, mock_repo
    )

    controller.load_card("card1")

    assert controller.get_current_card_id() == "card1"
    mock_repo.get_prints.assert_called_once_with("card1")
    stats_panel.update_stats.assert_called_once()


def test_preview_controller_clear(root, preview_components):
    mock_repo = Mock()

    image_label, stats_panel, text_widget, flavor_widget, print_selector = preview_components
    controller = CardPreviewController(
        image_label, stats_panel, text_widget, flavor_widget, print_selector, root, mock_repo
    )

    controller.clear()

    stats_panel.clear.assert_called_once()
    print_selector.clear.assert_called_once()
    assert controller.get_current_card_id() is None


def test_preview_controller_navigation(root, preview_components):
    mock_repo = Mock()
    mock_repo.get_prints.return_value = [
        {"print_id": 1, "set_name": "Set 1", "image_path": None},
        {"print_id": 2, "set_name": "Set 2", "image_path": None},
    ]
    mock_repo.get_card.return_value = {
        "id": "card1",
        "name": "Test Card",
        "type": "personality",
        "side": "FATE",
        "text": "Test text",
    }

    image_label, stats_panel, text_widget, flavor_widget, print_selector = preview_components
    controller = CardPreviewController(
        image_label, stats_panel, text_widget, flavor_widget, print_selector, root, mock_repo
    )

    controller.load_card("card1")
    assert controller.get_current_print_id() == 1

    controller.next_print()
    assert controller.get_current_print_id() == 2

    controller.prev_print()
    assert controller.get_current_print_id() == 1


def test_preview_controller_handles_none_text(root, preview_components):
    """Test that None values in text fields don't cause TclError."""
    mock_repo = Mock()
    mock_repo.get_prints.return_value = [
        {"print_id": 1, "set_name": "Test Set", "image_path": None, "flavor_text": None}
    ]
    mock_repo.get_card.return_value = {
        "id": "card1",
        "name": "Test Card",
        "type": "personality",
        "side": "FATE",
        "text": None,  # This can happen in database
    }

    image_label, stats_panel, text_widget, flavor_widget, print_selector = preview_components
    controller = CardPreviewController(
        image_label, stats_panel, text_widget, flavor_widget, print_selector, root, mock_repo
    )

    # This should not raise TclError
    controller.load_card("card1")

    # Verify text widgets are empty (not None)
    assert text_widget.get("1.0", tk.END).strip() == ""
    assert flavor_widget.get("1.0", tk.END).strip() == ""

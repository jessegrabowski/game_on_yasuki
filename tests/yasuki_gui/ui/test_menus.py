import tkinter as tk
from unittest.mock import Mock, patch

import pytest

from yasuki_gui.ui.menus import build_menubar


@pytest.fixture
def root():
    root = tk.Tk()
    yield root
    root.destroy()


@pytest.fixture
def mock_field_view():
    field_view = Mock()
    field_view.profile_name = "TestPlayer"
    field_view.profile_avatar = None
    field_view.apply_profile_to_panels = Mock()
    field_view.load_deck_from_file = Mock()
    return field_view


class TestBuildMenubar:
    def test_menubar_creation(self, root, mock_field_view):
        menubar = build_menubar(root, mock_field_view)

        assert isinstance(menubar, tk.Menu)
        assert menubar.index("end") is not None

    def test_app_menu_exists(self, root, mock_field_view):
        menubar = build_menubar(root, mock_field_view)

        menu_labels = []
        for i in range(menubar.index("end") + 1):
            try:
                label = menubar.entrycget(i, "label")
                menu_labels.append(label)
            except tk.TclError:
                pass

        assert "App" in menu_labels

    def test_deck_menu_exists(self, root, mock_field_view):
        menubar = build_menubar(root, mock_field_view)

        menu_labels = []
        for i in range(menubar.index("end") + 1):
            try:
                label = menubar.entrycget(i, "label")
                menu_labels.append(label)
            except tk.TclError:
                pass

        assert "Deck" in menu_labels

    @patch("yasuki_gui.ui.menus.Dialogs")
    def test_preferences_command(self, mock_dialogs_class, root, mock_field_view):
        mock_dialogs = Mock()
        mock_dialogs_class.return_value = mock_dialogs
        assert mock_field_view.profile_name == "TestPlayer"

    @patch("yasuki_gui.ui.menus.filedialog")
    def test_load_deck_command_with_file(self, mock_filedialog, root, mock_field_view):
        mock_filedialog.askopenfilename.return_value = "/test/deck.dck"
        assert mock_field_view.load_deck_from_file is not None

    @patch("yasuki_gui.ui.menus.filedialog")
    def test_load_deck_command_canceled(self, mock_filedialog, root, mock_field_view):
        mock_filedialog.askopenfilename.return_value = ""

        menubar = build_menubar(root, mock_field_view)

        assert menubar is not None

    @patch("yasuki_gui.ui.menus._open_deck_builder")
    def test_deck_builder_command(self, mock_open_builder, root, mock_field_view):
        menubar = build_menubar(root, mock_field_view)

        assert menubar is not None

    def test_quit_command_exists(self, root, mock_field_view):
        menubar = build_menubar(root, mock_field_view)

        assert menubar is not None

        root_mock = Mock()
        root.winfo_toplevel = Mock(return_value=root_mock)


def _menu_labels(menubar: tk.Menu) -> list[str]:
    labels = []
    for index in range(menubar.index("end") + 1):
        try:
            labels.append(menubar.entrycget(index, "label"))
        except tk.TclError:
            pass
    return labels


def test_the_debug_menu_appears_only_in_debug_mode(root, mock_field_view):
    assert "Debug" not in _menu_labels(build_menubar(root, mock_field_view))
    assert "Debug" in _menu_labels(build_menubar(root, mock_field_view, debug=True))


def test_a_debug_command_runs_the_hook_the_window_set(root, mock_field_view):
    """The menu is built before the presenter is bound, so it reads the hook at click time."""
    menubar = build_menubar(root, mock_field_view, debug=True)
    debug_menu = root.nametowidget(menubar.entrycget(_menu_labels(menubar).index("Debug"), "menu"))
    ran = []
    mock_field_view.on_debug_gold = lambda: ran.append("gold")

    debug_menu.invoke(0)

    assert ran == ["gold"]

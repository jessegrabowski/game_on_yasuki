import tkinter as tk
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.game_pieces.constants import Side
from app.gui.ui.images import (
    load_image,
    load_back_image,
    clear_image_cache,
    ImageProvider,
)


@pytest.fixture
def root():
    root = tk.Tk()
    yield root
    root.destroy()


class TestLoadImage:
    def test_load_image_none_path(self, root):
        result = load_image(None, False, False, root)
        assert result is None

    @patch("app.gui.ui.images.Image")
    @patch("app.gui.ui.images.ImageTk")
    def test_load_image_basic(self, mock_imagetk, mock_image, root):
        mock_img = Mock()
        mock_image.open.return_value = mock_img
        mock_img.resize.return_value = mock_img
        mock_imagetk.PhotoImage.return_value = Mock()

        test_path = Path("/test/path.jpg")
        result = load_image(test_path, False, False, root)

        mock_image.open.assert_called_once_with(str(test_path))
        assert result is not None

    @patch("app.gui.ui.images.Image")
    @patch("app.gui.ui.images.ImageTk")
    def test_load_image_bowed(self, mock_imagetk, mock_image, root):
        mock_img = Mock()
        mock_image.open.return_value = mock_img
        mock_img.rotate.return_value = mock_img
        mock_img.resize.return_value = mock_img
        mock_imagetk.PhotoImage.return_value = Mock()

        test_path = Path("/test/path.jpg")
        load_image(test_path, True, False, root)

        mock_img.rotate.assert_called_with(-90, expand=True)

    @patch("app.gui.ui.images.Image")
    @patch("app.gui.ui.images.ImageTk")
    def test_load_image_inverted(self, mock_imagetk, mock_image, root):
        mock_img = Mock()
        mock_image.open.return_value = mock_img
        mock_img.rotate.return_value = mock_img
        mock_img.resize.return_value = mock_img
        mock_imagetk.PhotoImage.return_value = Mock()

        test_path = Path("/test/path.jpg")
        load_image(test_path, False, True, root)

        mock_img.rotate.assert_called_with(180, expand=True)

    def test_load_image_caching(self, root):
        clear_image_cache()

        cache_info_before = load_image.cache_info()
        initial_hits = cache_info_before.hits

        test_path = Path("/nonexistent/path.jpg")
        load_image(test_path, False, False, root)
        load_image(test_path, False, False, root)

        cache_info_after = load_image.cache_info()
        assert cache_info_after.hits > initial_hits


class TestLoadBackImage:
    @patch("app.gui.ui.images.load_image")
    def test_load_back_image_fate(self, mock_load, root):
        load_back_image(Side.FATE, False, False, None, root)

        mock_load.assert_called_once()
        args = mock_load.call_args[0]
        assert args[1] is False
        assert args[2] is False

    @patch("app.gui.ui.images.load_image")
    def test_load_back_image_dynasty(self, mock_load, root):
        load_back_image(Side.DYNASTY, False, False, None, root)

        mock_load.assert_called_once()
        args = mock_load.call_args[0]
        assert args[1] is False

    @patch("app.gui.ui.images.load_image")
    def test_load_back_image_custom_path(self, mock_load, root):
        custom_path = Path("/custom/back.jpg")
        load_back_image(Side.FATE, False, False, custom_path, root)

        mock_load.assert_called_once()
        args = mock_load.call_args[0]
        assert args[0] == custom_path


def test_clear_image_cache():
    clear_image_cache()
    cache_info = load_image.cache_info()
    assert cache_info.currsize == 0


class TestImageProvider:
    def test_initialization(self, root):
        provider = ImageProvider(root)
        assert provider.master is root

    @patch("app.gui.ui.images.load_image")
    def test_front_image(self, mock_load, root):
        provider = ImageProvider(root)
        test_path = Path("/test/front.jpg")

        provider.front(test_path, False, False)

        mock_load.assert_called_once_with(test_path, False, False, master=root)

    @patch("app.gui.ui.images.load_back_image")
    def test_back_image(self, mock_load_back, root):
        provider = ImageProvider(root)

        provider.back(Side.FATE, True, False, None)

        mock_load_back.assert_called_once_with(Side.FATE, True, False, None, master=root)

    @patch("app.gui.ui.images.clear_image_cache")
    def test_clear(self, mock_clear, root):
        provider = ImageProvider(root)

        provider.clear()

        mock_clear.assert_called_once()

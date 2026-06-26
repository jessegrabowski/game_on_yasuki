import asyncio
import importlib

import pytest

from yasuki_web.config import allowed_origins


def test_origins_parsed_from_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    assert allowed_origins() == ["https://a.example", "https://b.example"]


def test_wildcard_origin_is_rejected(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://play.example,*")
    with pytest.raises(ValueError):
        allowed_origins()


def test_api_config_shape(monkeypatch):
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.setenv("IMAGE_BASE_URL", "/images")
    main = importlib.reload(importlib.import_module("yasuki_web.main"))
    assert asyncio.run(main.config()) == {"image_base_url": "/images", "debug": False}


@pytest.mark.parametrize(
    "value,expected",
    [("1", True), ("true", True), ("YES", True), ("on", True), ("0", False), ("", False)],
)
def test_debug_env_parsing(monkeypatch, value, expected):
    monkeypatch.setenv("DEBUG", value)
    main = importlib.reload(importlib.import_module("yasuki_web.main"))
    assert asyncio.run(main.config())["debug"] is expected

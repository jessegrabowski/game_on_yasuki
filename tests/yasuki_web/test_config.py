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
    monkeypatch.delenv("YASUKI_DEV_LOGIN", raising=False)
    monkeypatch.setenv("IMAGE_BASE_URL", "/images")
    main = importlib.reload(importlib.import_module("yasuki_web.main"))
    assert asyncio.run(main.config()) == {
        "image_base_url": "/images",
        "debug": False,
        "dev_login": False,
    }


def test_api_config_advertises_dev_login_when_enabled(monkeypatch):
    monkeypatch.setenv("YASUKI_DEV_LOGIN", "1")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    main = importlib.reload(importlib.import_module("yasuki_web.main"))
    assert asyncio.run(main.config())["dev_login"] is True


@pytest.mark.parametrize(
    "value,expected",
    [("1", True), ("true", True), ("YES", True), ("on", True), ("0", False), ("", False)],
)
def test_debug_env_parsing(monkeypatch, value, expected):
    monkeypatch.setenv("DEBUG", value)
    main = importlib.reload(importlib.import_module("yasuki_web.main"))
    assert asyncio.run(main.config())["debug"] is expected

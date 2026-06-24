import pytest

from yasuki_web.config import allowed_origins


def test_origins_parsed_from_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    assert allowed_origins() == ["https://a.example", "https://b.example"]


def test_wildcard_origin_is_rejected(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://play.example,*")
    with pytest.raises(ValueError):
        allowed_origins()

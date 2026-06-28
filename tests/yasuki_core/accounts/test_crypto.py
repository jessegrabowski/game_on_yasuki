import pytest

from yasuki_core.accounts import crypto


@pytest.fixture(autouse=True)
def _pepper(monkeypatch):
    monkeypatch.setenv("YASUKI_EMAIL_HMAC_PEPPER", "test-pepper")


def test_email_index_is_case_and_whitespace_insensitive():
    messy = crypto.email_blind_index("  Ada@Example.com ")
    clean = crypto.email_blind_index("ada@example.com")
    assert messy == clean


def test_email_index_distinguishes_different_addresses():
    ada = crypto.email_blind_index("ada@example.com")
    kenji = crypto.email_blind_index("kenji@example.com")
    assert ada != kenji


def test_email_index_depends_on_the_pepper(monkeypatch):
    one = crypto.email_blind_index("ada@example.com")
    monkeypatch.setenv("YASUKI_EMAIL_HMAC_PEPPER", "a-different-pepper")
    assert crypto.email_blind_index("ada@example.com") != one


def test_email_index_requires_a_pepper(monkeypatch):
    monkeypatch.delenv("YASUKI_EMAIL_HMAC_PEPPER", raising=False)
    with pytest.raises(RuntimeError):
        crypto.email_blind_index("ada@example.com")


def test_sub_index_is_deterministic_and_distinguishes_subjects():
    assert crypto.sub_blind_index("google-123") == crypto.sub_blind_index("google-123")
    assert crypto.sub_blind_index("google-123") != crypto.sub_blind_index("google-456")


def test_sub_and_email_indexes_of_the_same_string_differ():
    # Distinct HMAC inputs must not collide across the two banlist columns.
    assert crypto.sub_blind_index("ada@example.com") != crypto.email_blind_index("ada@example.com")


def test_sub_index_requires_a_pepper(monkeypatch):
    monkeypatch.delenv("YASUKI_EMAIL_HMAC_PEPPER", raising=False)
    with pytest.raises(RuntimeError):
        crypto.sub_blind_index("google-123")


def test_session_token_hash_is_deterministic_and_not_the_raw_token():
    token = crypto.new_session_token()
    assert crypto.hash_session_token(token) == crypto.hash_session_token(token)
    assert token.encode() != crypto.hash_session_token(token)


def test_session_tokens_are_unique():
    assert crypto.new_session_token() != crypto.new_session_token()

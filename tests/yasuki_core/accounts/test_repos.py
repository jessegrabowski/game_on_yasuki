from datetime import timedelta

import pytest

from yasuki_core.accounts import oauth_state, sessions, users


@pytest.fixture(autouse=True)
def _pepper(monkeypatch):
    monkeypatch.setenv("YASUKI_EMAIL_HMAC_PEPPER", "test-pepper")


def test_upsert_inserts_then_refreshes_without_clobbering_display_name(accounts_conn):
    user = users.upsert_user(accounts_conn, "google-1", "ada@example.com", True, "Ada")
    assert user["display_name"] == "Ada"
    assert user["is_banned"] is False

    again = users.upsert_user(
        accounts_conn, "google-1", "ada@example.com", True, "ShouldNotApply", avatar_url="http://p"
    )
    assert again["id"] == user["id"]
    assert again["display_name"] == "Ada"
    assert again["avatar_url"] == "http://p"


def test_get_user_returns_row_or_none(accounts_conn):
    created = users.upsert_user(accounts_conn, "g", "e@example.com", True, "E")
    assert users.get_user(accounts_conn, created["id"])["google_sub"] == "g"
    assert users.get_user(accounts_conn, 999999) is None


def test_session_round_trip_resolves_to_its_user(accounts_conn):
    user = users.upsert_user(accounts_conn, "g", "e@example.com", True, "E")
    token = sessions.create_session(accounts_conn, user["id"], timedelta(days=1))
    assert sessions.resolve_session(accounts_conn, token)["id"] == user["id"]


def test_resolved_session_carries_the_identity_the_web_layer_seats_by(accounts_conn):
    # The WS handshake seats players by the resolved session's id and display_name; pin those keys
    # against the real query so a rename can't break seating while the web tests fake the resolver.
    user = users.upsert_user(accounts_conn, "g", "ada@example.com", True, "Ada")
    token = sessions.create_session(accounts_conn, user["id"], timedelta(days=1))
    resolved = sessions.resolve_session(accounts_conn, token)
    assert resolved["id"] == user["id"]
    assert resolved["display_name"] == "Ada"


def test_expired_session_does_not_resolve(accounts_conn):
    user = users.upsert_user(accounts_conn, "g", "e@example.com", True, "E")
    token = sessions.create_session(accounts_conn, user["id"], timedelta(seconds=-1))
    assert sessions.resolve_session(accounts_conn, token) is None


def test_banned_user_session_does_not_resolve(accounts_conn):
    user = users.upsert_user(accounts_conn, "g", "e@example.com", True, "E")
    token = sessions.create_session(accounts_conn, user["id"], timedelta(days=1))
    with accounts_conn.cursor() as cur:
        cur.execute("UPDATE users SET is_banned = true WHERE id = %s", (user["id"],))
    assert sessions.resolve_session(accounts_conn, token) is None


def test_unknown_and_revoked_tokens_do_not_resolve(accounts_conn):
    user = users.upsert_user(accounts_conn, "g", "e@example.com", True, "E")
    token = sessions.create_session(accounts_conn, user["id"], timedelta(days=1))
    assert sessions.resolve_session(accounts_conn, "not-a-real-token") is None
    sessions.delete_session(accounts_conn, token)
    assert sessions.resolve_session(accounts_conn, token) is None


def test_delete_user_sessions_revokes_every_session(accounts_conn):
    user = users.upsert_user(accounts_conn, "g", "e@example.com", True, "E")
    first = sessions.create_session(accounts_conn, user["id"], timedelta(days=1))
    second = sessions.create_session(accounts_conn, user["id"], timedelta(days=1))
    sessions.delete_user_sessions(accounts_conn, user["id"])
    assert sessions.resolve_session(accounts_conn, first) is None
    assert sessions.resolve_session(accounts_conn, second) is None


def test_oauth_login_state_is_single_use(accounts_conn):
    oauth_state.stash_login(accounts_conn, "state-1", "nonce-1", "verifier-1", redirect_to="/lobby")
    popped = oauth_state.pop_login(accounts_conn, "state-1", timedelta(minutes=10))
    assert popped == {"nonce": "nonce-1", "code_verifier": "verifier-1", "redirect_to": "/lobby"}
    assert oauth_state.pop_login(accounts_conn, "state-1", timedelta(minutes=10)) is None


def test_oauth_login_rejects_stale_state(accounts_conn):
    oauth_state.stash_login(accounts_conn, "state-2", "n", "v")
    assert oauth_state.pop_login(accounts_conn, "state-2", timedelta(seconds=0)) is None


def test_purge_stale_logins_removes_aged_rows(accounts_conn):
    oauth_state.stash_login(accounts_conn, "state-3", "n", "v")
    assert oauth_state.purge_stale_logins(accounts_conn, timedelta(seconds=0)) == 1
    assert oauth_state.pop_login(accounts_conn, "state-3", timedelta(minutes=10)) is None

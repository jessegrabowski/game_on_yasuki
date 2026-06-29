from datetime import timedelta

import pytest

from yasuki_core.accounts import banlist, oauth_state, sessions, users


@pytest.fixture(autouse=True)
def _pepper(monkeypatch):
    monkeypatch.setenv("YASUKI_EMAIL_HMAC_PEPPER", "test-pepper")


def test_upsert_inserts_then_refreshes_without_clobbering_display_name(accounts_conn):
    user = users.upsert_user(accounts_conn, "google-1", "ada@example.com", True, "Ada")
    assert user["display_name"] == "Ada"
    assert user["is_banned"] is False

    again = users.upsert_user(accounts_conn, "google-1", "ada@example.com", True, "ShouldNotApply")
    assert again["id"] == user["id"]
    assert again["display_name"] == "Ada"


def test_upsert_reports_created_only_on_the_first_sign_in(accounts_conn):
    assert users.upsert_user(accounts_conn, "g", "e@example.com", True, "First")["created"] is True
    assert users.upsert_user(accounts_conn, "g", "e@example.com", True, "Again")["created"] is False


def test_set_display_name_updates_the_row(accounts_conn):
    user = users.upsert_user(accounts_conn, "g", "e@example.com", True, "Old")
    assert users.set_display_name(accounts_conn, user["id"], "New")["display_name"] == "New"
    assert users.get_user(accounts_conn, user["id"])["display_name"] == "New"
    assert users.set_display_name(accounts_conn, 999999, "Ghost") is None


def test_set_avatar_stores_and_clears_the_spec(accounts_conn):
    user = users.upsert_user(accounts_conn, "g", "e@example.com", True, "Ada")
    spec = {
        "card_id": "doji",
        "image_path": "sets/x/doji.jpg",
        "crop": {"left": 0.1, "top": 0.1, "right": 0.4, "bottom": 0.4},
    }
    assert users.set_avatar(accounts_conn, user["id"], spec)["avatar"] == spec
    assert users.get_user(accounts_conn, user["id"])["avatar"] == spec
    assert users.set_avatar(accounts_conn, user["id"], None)["avatar"] is None


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


def _give_user_a_deck(accounts_conn, user_id: int) -> int:
    with accounts_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO decks (slug, owner_id, name) VALUES ('s', %s, 'D') RETURNING id",
            (user_id,),
        )
        deck_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO deck_cards (deck_id, card_id, card_name, side, quantity) "
            "VALUES (%s, 'c', 'C', 'dynasty', 1)",
            (deck_id,),
        )
        return deck_id


def test_delete_account_erases_the_user_and_cascades_sessions_and_decks(accounts_conn):
    user = users.upsert_user(accounts_conn, "sub", "ada@example.com", True, "Ada")
    sessions.create_session(accounts_conn, user["id"], timedelta(days=1))
    deck_id = _give_user_a_deck(accounts_conn, user["id"])

    assert users.delete_account(accounts_conn, user["id"]) is True
    assert users.get_user(accounts_conn, user["id"]) is None
    with accounts_conn.cursor() as cur:
        for table, column in (("sessions", "user_id"), ("decks", "owner_id")):
            cur.execute(f"SELECT count(*) AS n FROM {table} WHERE {column} = %s", (user["id"],))
            assert cur.fetchone()["n"] == 0
        cur.execute("SELECT count(*) AS n FROM deck_cards WHERE deck_id = %s", (deck_id,))
        assert cur.fetchone()["n"] == 0


def test_deleting_a_user_in_good_standing_leaves_no_tombstone(accounts_conn):
    user = users.upsert_user(accounts_conn, "clean", "clean@example.com", True, "Clean")
    users.delete_account(accounts_conn, user["id"])
    assert banlist.is_banned(accounts_conn, "clean", "clean@example.com") is False


def test_a_retained_tombstone_blocks_a_banned_identity_after_deletion(accounts_conn):
    user = users.upsert_user(accounts_conn, "bad", "bad@example.com", True, "Bad")
    users.ban_user(accounts_conn, user["id"], "spam")
    users.delete_account(accounts_conn, user["id"])
    assert users.get_user(accounts_conn, user["id"]) is None
    assert banlist.is_banned(accounts_conn, "bad", "bad@example.com") is True


def test_ban_user_flags_revokes_sessions_and_tombstones(accounts_conn):
    user = users.upsert_user(accounts_conn, "bad", "bad@example.com", True, "Bad")
    token = sessions.create_session(accounts_conn, user["id"], timedelta(days=1))
    assert users.ban_user(accounts_conn, user["id"], "cheating") is True
    assert sessions.resolve_session(accounts_conn, token) is None
    assert banlist.is_banned(accounts_conn, "bad", "bad@example.com") is True


def test_ban_user_rolls_back_when_tombstoning_fails(accounts_conn, monkeypatch):
    user = users.upsert_user(accounts_conn, "bad", "bad@example.com", True, "Bad")
    token = sessions.create_session(accounts_conn, user["id"], timedelta(days=1))

    def boom(*args, **kwargs):
        raise RuntimeError("tombstone exploded")

    monkeypatch.setattr(banlist, "tombstone", boom)
    with pytest.raises(RuntimeError):
        users.ban_user(accounts_conn, user["id"], "spam")

    # The whole flow rolled back: the user is not half-banned and their session still resolves.
    assert users.get_user(accounts_conn, user["id"])["is_banned"] is False
    assert sessions.resolve_session(accounts_conn, token) is not None


def test_banlist_blocks_a_new_google_account_on_a_banned_email(accounts_conn):
    user = users.upsert_user(accounts_conn, "old-sub", "ban@example.com", True, "B")
    users.ban_user(accounts_conn, user["id"])
    assert banlist.is_banned(accounts_conn, "a-brand-new-sub", "ban@example.com") is True


def test_banlist_blocks_the_same_google_account_on_a_new_email(accounts_conn):
    user = users.upsert_user(accounts_conn, "same-sub", "first@example.com", True, "S")
    users.ban_user(accounts_conn, user["id"])
    assert banlist.is_banned(accounts_conn, "same-sub", "moved@example.com") is True


def test_banlist_misses_an_unrelated_identity(accounts_conn):
    assert banlist.is_banned(accounts_conn, "nobody", "nobody@example.com") is False


def test_delete_account_and_ban_report_false_for_an_unknown_user(accounts_conn):
    assert users.delete_account(accounts_conn, 999999) is False
    assert users.ban_user(accounts_conn, 999999) is False


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

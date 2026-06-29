from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from yasuki_web import auth, saved_decks
from yasuki_web.main import app

from yasuki_core.accounts import decks, sessions, users

# A small card universe shaped like get_cards_by_names output — the contract the save path resolves
# against. The card DB is faked so these tests don't depend on real card data.
RECORDS = [
    {"card_id": "kyuden_hida", "name": "Kyuden Hida", "types": ["Stronghold"], "clans": ["Crab"]},
    {"card_id": "hida_kisada", "name": "Hida Kisada", "types": ["Personality"], "clans": ["Crab"]},
    {"card_id": "kisada_alt", "name": "Kisada Alt", "types": ["Personality"], "clans": ["Crab"]},
    {"card_id": "ambush", "name": "Ambush", "types": ["Strategy"], "clans": []},
]

DECK_YAML = """\
name: Crab Beats
Pre-Game:
  - Kyuden Hida
Dynasty:
  - 3x Hida Kisada [Pearl Edition] {art: Kisada Alt [Gold]}
Fate:
  - 2x Ambush
"""


@pytest.fixture
def client(monkeypatch, accounts_conn):
    monkeypatch.setenv("YASUKI_EMAIL_HMAC_PEPPER", "test-pepper")

    @contextmanager
    def fake_conn():
        yield accounts_conn

    monkeypatch.setattr(auth, "get_accounts_connection", fake_conn)
    monkeypatch.setattr(saved_decks, "get_accounts_connection", fake_conn)
    monkeypatch.setattr(saved_decks, "get_cards_by_names", lambda names: RECORDS)
    monkeypatch.setattr(saved_decks, "card_display_names", lambda ids: {"kisada_alt": "Kisada Alt"})
    return TestClient(app)


def _login(client, accounts_conn, *, sub="g", name="Ada"):
    user = users.upsert_user(accounts_conn, sub, f"{sub}@example.com", True, name)
    users.set_approved(accounts_conn, user["id"], True)  # deck routes are approval-gated
    token = sessions.create_session(accounts_conn, user["id"], timedelta(days=1))
    client.cookies.set("yasuki_session", token)
    return user


def _save(client, **overrides):
    body = {"name": "Crab Beats", "yaml": DECK_YAML, "visibility": "private", **overrides}
    return client.post("/api/me/decks", json=body)


def _variant_keys(cards: list[dict]) -> set[tuple]:
    return {
        (
            c["card_id"],
            c["side"],
            c["quantity"],
            c["set_name"],
            c["art_donor_card_id"],
            c["art_donor_set"],
        )
        for c in cards
    }


def _expected_keys() -> set[tuple]:
    resolved = decks.deck_from_yaml(DECK_YAML, decks.build_name_index(RECORDS))
    return {
        (c.card_id, c.side, c.quantity, c.set_name, c.art_donor_card_id, c.art_donor_set)
        for c in resolved
    }


def test_save_list_and_read_round_trip_the_cards(client, accounts_conn):
    _login(client, accounts_conn)
    slug = _save(client, visibility="public").json()["deck"]["slug"]

    listed = client.get("/api/me/decks").json()["decks"]
    assert [d["slug"] for d in listed] == [slug]
    assert (listed[0]["dynasty_count"], listed[0]["fate_count"]) == (3, 2)
    assert listed[0]["stronghold_card_id"] == "kyuden_hida" and listed[0]["clan"] == "Crab"

    read = client.get(f"/api/decks/{slug}").json()
    assert _variant_keys(read["cards"]) == _expected_keys()
    # The returned YAML, re-resolved, is the same deck the lobby would load — the pick path matches
    # the direct YAML path.
    relisted = decks.deck_from_yaml(read["yaml"], decks.build_name_index(RECORDS))
    assert {(c.card_id, c.quantity, c.art_donor_card_id) for c in relisted} == {
        (c["card_id"], c["quantity"], c["art_donor_card_id"]) for c in read["cards"]
    }


def test_anonymous_cannot_save(client):
    assert _save(client).status_code == 401


def test_anonymous_can_read_public_and_unlisted_decks_but_not_private(client, accounts_conn):
    _login(client, accounts_conn)
    public_slug = _save(client, visibility="public").json()["deck"]["slug"]
    unlisted_slug = _save(client, visibility="unlisted").json()["deck"]["slug"]
    private_slug = _save(client, visibility="private").json()["deck"]["slug"]

    client.cookies.clear()
    assert client.get(f"/api/decks/{public_slug}").status_code == 200
    assert client.get(f"/api/decks/{unlisted_slug}").status_code == 200
    # A private deck 404s rather than 403, so its existence stays hidden.
    assert client.get(f"/api/decks/{private_slug}").status_code == 404


def test_an_owner_can_read_their_own_private_deck(client, accounts_conn):
    _login(client, accounts_conn)
    slug = _save(client, visibility="private").json()["deck"]["slug"]
    assert client.get(f"/api/decks/{slug}").status_code == 200


def test_a_private_deck_is_hidden_from_other_users(client, accounts_conn):
    _login(client, accounts_conn, sub="owner", name="Ada")
    slug = _save(client, visibility="private").json()["deck"]["slug"]

    _login(client, accounts_conn, sub="intruder", name="Kenji")
    assert client.get(f"/api/decks/{slug}").status_code == 404


def test_save_rejects_an_unknown_card(client, accounts_conn):
    _login(client, accounts_conn)
    resp = _save(client, yaml="Dynasty:\n  - Nonexistent Card\n")
    assert resp.status_code == 400
    assert resp.json()["detail"]["cards"] == ["Nonexistent Card"]


def test_save_rejects_an_overlong_name(client, accounts_conn):
    _login(client, accounts_conn)
    assert _save(client, name="N" * 81).status_code == 422


def test_save_rejects_too_many_copies_of_one_entry(client, accounts_conn):
    _login(client, accounts_conn)
    resp = _save(client, yaml="Dynasty:\n  - 101x Hida Kisada\n")
    assert resp.status_code == 422


def test_save_rejects_a_deck_with_no_recognizable_cards(client, accounts_conn):
    _login(client, accounts_conn)
    assert _save(client, yaml="Dynasty:\n").status_code == 422


def test_save_rejects_too_many_distinct_entries(client, accounts_conn, monkeypatch):
    monkeypatch.setattr(saved_decks, "MAX_DECK_ENTRIES", 1)
    _login(client, accounts_conn)
    resp = _save(client, yaml="Dynasty:\n  - Hida Kisada\nFate:\n  - Ambush\n")
    assert resp.status_code == 422


def test_save_enforces_the_per_user_deck_limit(client, accounts_conn, monkeypatch):
    monkeypatch.setattr(saved_decks, "MAX_DECKS_PER_USER", 1)
    _login(client, accounts_conn)
    assert _save(client).status_code == 201
    assert _save(client).status_code == 422


def test_delete_removes_a_deck_from_listing_and_sharing(client, accounts_conn):
    _login(client, accounts_conn)
    slug = _save(client, visibility="public").json()["deck"]["slug"]
    assert client.delete(f"/api/me/decks/{slug}").status_code == 200
    assert client.get("/api/me/decks").json()["decks"] == []
    assert client.get(f"/api/decks/{slug}").status_code == 404


def test_delete_cannot_touch_another_users_deck(client, accounts_conn):
    _login(client, accounts_conn, sub="owner", name="Ada")
    slug = _save(client, visibility="public").json()["deck"]["slug"]

    _login(client, accounts_conn, sub="intruder", name="Kenji")
    assert client.delete(f"/api/me/decks/{slug}").status_code == 404
    client.cookies.clear()
    assert client.get(f"/api/decks/{slug}").status_code == 200  # still there, untouched

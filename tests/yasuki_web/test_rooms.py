import pytest
from fastapi.testclient import TestClient

from yasuki_web.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_delete_requires_token_header(client):
    rid = client.post("/api/rooms", json={"max_players": 2}).json()["room_id"]
    # No X-Delete-Token header at all -> 422 (required header missing).
    assert client.delete(f"/api/rooms/{rid}").status_code == 422


def test_delete_rejects_wrong_token(client):
    rid = client.post("/api/rooms", json={"max_players": 2}).json()["room_id"]
    r = client.delete(f"/api/rooms/{rid}", headers={"X-Delete-Token": "wrong"})
    assert r.status_code == 403


def test_delete_accepts_correct_token(client):
    created = client.post("/api/rooms", json={"max_players": 2}).json()
    rid, token = created["room_id"], created["delete_token"]
    r = client.delete(f"/api/rooms/{rid}", headers={"X-Delete-Token": token})
    assert r.status_code == 200
    # Room is gone afterwards.
    assert client.get(f"/api/rooms/{rid}").status_code == 404


def test_room_name_length_is_bounded(client):
    assert client.post("/api/rooms", json={"room_name": "N" * 100}).status_code == 422
    assert client.post("/api/rooms", json={"room_name": "N" * 60}).status_code == 201


def test_unknown_deck_returns_422(client):
    # Rejected by the enum allowlist before any DB query, so this runs without a database.
    assert client.get("/api/card-types-by-deck?deck=bogus").status_code == 422

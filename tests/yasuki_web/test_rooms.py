def test_delete_requires_token_header(client):
    rid = client.post("/api/rooms", json={"max_players": 2}).json()["room_id"]
    # Missing a required header is a 422, not a 403.
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
    assert client.get(f"/api/rooms/{rid}").status_code == 404


def test_room_name_length_is_bounded(client):
    assert client.post("/api/rooms", json={"room_name": "N" * 100}).status_code == 422
    assert client.post("/api/rooms", json={"room_name": "N" * 60}).status_code == 201


def test_room_payload_exposes_expected_keys(client):
    # The lobby JS (and its fixtures.js) consume these exact keys; pin the shape here so a regression
    # fails a test instead of only surfacing in the browser after a deploy.
    created = client.post("/api/rooms", json={"room_name": "Table", "max_players": 2}).json()
    assert created.keys() >= {"room_id", "room", "delete_token", "websocket_url"}
    room = created["room"]
    assert room.keys() >= {"id", "name", "max_players", "players", "state", "created_at"}
    assert "delete_token" not in room
    assert client.get("/api/rooms").json().keys() >= {"rooms", "count", "total_rooms"}


def test_unknown_deck_returns_422(client):
    # Rejected by the enum allowlist before any DB query, so this runs without a database.
    assert client.get("/api/card-types-by-deck?deck=bogus").status_code == 422

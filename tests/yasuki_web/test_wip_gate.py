import base64

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from yasuki_web.main import app
from yasuki_web.wip_gate import websocket_access_ok


@pytest.fixture
def client():
    return TestClient(app)


class _FakeWebSocket:
    def __init__(self, authorization: str | None):
        self.headers = {"authorization": authorization} if authorization is not None else {}


def _make_room(client, wip_auth_header) -> str:
    return client.post("/api/rooms", json={"max_players": 2}, headers=wip_auth_header).json()[
        "room_id"
    ]


def test_top_secret_requires_password(client):
    r = client.get("/top-secret.html")
    assert r.status_code == 401
    assert r.headers["www-authenticate"].lower().startswith("basic")


def test_top_secret_rejects_wrong_password(client):
    r = client.get("/top-secret.html", auth=("yasuki", "nope"))
    assert r.status_code == 401


def test_rooms_api_requires_password(client):
    assert client.post("/api/rooms", json={"max_players": 2}).status_code == 401


def test_rooms_api_accepts_password(client, wip_auth_header):
    r = client.post("/api/rooms", json={"max_players": 2}, headers=wip_auth_header)
    assert r.status_code == 201


def test_ws_handshake_requires_password(client, wip_auth_header):
    room_id = _make_room(client, wip_auth_header)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/{room_id}"):
            pass
    assert exc.value.code == 4401


def test_unset_password_disables_wip(client, monkeypatch, wip_auth_header):
    # With no password configured the gate fails closed across all three surfaces (page, rooms API,
    # WS handshake): the HTTP routes look absent and even valid-looking credentials cannot open it.
    monkeypatch.delenv("WIP_PLAY_PASSWORD", raising=False)
    assert client.get("/top-secret.html", headers=wip_auth_header).status_code == 404
    assert (
        client.post("/api/rooms", json={"max_players": 2}, headers=wip_auth_header).status_code
        == 404
    )
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/any-room", headers=wip_auth_header):
            pass
    assert exc.value.code == 4401


def test_websocket_access_ok_accepts_valid_credentials(wip_auth_header):
    assert websocket_access_ok(_FakeWebSocket(wip_auth_header["Authorization"])) is True


def test_websocket_access_ok_rejects_wrong_password():
    wrong = "Basic " + base64.b64encode(b"yasuki:wrong").decode()
    assert websocket_access_ok(_FakeWebSocket(wrong)) is False


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "Bearer sometoken",
        "Basic !!!not-base64",
        "Basic " + base64.b64encode(b"no-colon-here").decode(),
    ],
)
def test_websocket_access_ok_rejects_malformed_header(header):
    assert websocket_access_ok(_FakeWebSocket(header)) is False

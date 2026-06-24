import pytest
from starlette.websockets import WebSocketDisconnect

from yasuki_web import websocket as ws_module
from yasuki_web.websocket import WS_MSG_BURST, _origin_allowed


def _make_room(client) -> str:
    return client.post("/api/rooms", json={"max_players": 2}).json()["room_id"]


def test_ping_pong(client):
    room_id = _make_room(client)
    with client.websocket_connect(f"/ws/{room_id}") as ws:
        ws.send_json({"type": "PING", "room": room_id})
        assert ws.receive_json() == {"type": "PONG"}


def test_join_returns_hello_with_name(client):
    room_id = _make_room(client)
    with client.websocket_connect(f"/ws/{room_id}") as ws:
        ws.send_json({"type": "JOIN", "room": room_id, "join": {"name": "Ada"}})
        hello = ws.receive_json()
        assert hello["type"] == "HELLO"
        assert hello["you"] == "Ada"


def test_malformed_frame_closes_connection(client):
    room_id = _make_room(client)
    with client.websocket_connect(f"/ws/{room_id}") as ws:
        ws.send_text("not json at all")
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1003


def test_overlong_player_name_rejected(client):
    # REST caps names at 50; the WS path must enforce the same bound via the schema.
    room_id = _make_room(client)
    with client.websocket_connect(f"/ws/{room_id}") as ws:
        ws.send_json({"type": "JOIN", "room": room_id, "join": {"name": "N" * 51}})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1003


def test_unknown_action_kind_rejected(client):
    room_id = _make_room(client)
    with client.websocket_connect(f"/ws/{room_id}") as ws:
        ws.send_json({"type": "JOIN", "room": room_id, "join": {"name": "Ada"}})
        ws.receive_json()  # HELLO
        ws.receive_json()  # STATE broadcast
        ws.send_json({"type": "ACTION", "room": room_id, "action": {"kind": "HACK"}})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1003


def test_message_flood_is_throttled(client):
    # The token bucket holds WS_MSG_BURST messages; a faster-than-refill flood drains it and closes.
    room_id = _make_room(client)
    with client.websocket_connect(f"/ws/{room_id}") as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            for _ in range(WS_MSG_BURST + 5):
                ws.send_json({"type": "PING", "room": room_id})
                ws.receive_json()
        assert exc.value.code == 1008


def test_cross_origin_handshake_rejected(client):
    room_id = _make_room(client)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/{room_id}", headers={"origin": "https://evil.example"}):
            pass
    assert exc.value.code == 4403


class _OriginWS:
    def __init__(self, **headers):
        self.headers = headers


def test_origin_allowed_accepts_configured_origin(monkeypatch):
    monkeypatch.setattr(ws_module, "ALLOWED_WS_ORIGINS", frozenset({"https://play.example"}))
    assert _origin_allowed(_OriginWS(origin="https://play.example", host="play.example")) is True


def test_origin_allowed_rejects_unlisted_origin(monkeypatch):
    monkeypatch.setattr(ws_module, "ALLOWED_WS_ORIGINS", frozenset({"https://play.example"}))
    assert _origin_allowed(_OriginWS(origin="https://evil.example", host="play.example")) is False


def test_origin_allowed_permits_same_origin(monkeypatch):
    # The page that opened the socket is served by this app, so its Origin matches the Host even when
    # it isn't on the explicit allowlist.
    monkeypatch.setattr(ws_module, "ALLOWED_WS_ORIGINS", frozenset())
    assert _origin_allowed(_OriginWS(origin="https://play.example", host="play.example")) is True


def test_origin_allowed_permits_missing_origin():
    # Native (non-browser) clients send no Origin header.
    assert _origin_allowed(_OriginWS(host="play.example")) is True

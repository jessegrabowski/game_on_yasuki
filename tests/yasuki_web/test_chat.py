import asyncio

import pytest
from starlette.websockets import WebSocketDisconnect

from yasuki_web.websocket import GameRoom


def _join(ws, room_id, name):
    ws.send_json({"type": "JOIN", "room": room_id, "join": {"name": name}})
    ws.receive_json()  # HELLO
    ws.receive_json()  # STATE


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


def test_handle_chat_broadcasts_to_every_joined_player():
    async def scenario():
        room = GameRoom("r1")
        ada, kenji = _FakeWS(), _FakeWS()
        room.players = {ada: "Ada", kenji: "Kenji"}
        await room.handle_chat(ada, "hello")
        return ada.sent, kenji.sent

    ada_sent, kenji_sent = asyncio.run(scenario())
    expected = {"type": "CHAT", "room": "r1", "from": "Ada", "text": "hello"}
    assert ada_sent == [expected]
    assert kenji_sent == [expected]


def test_handle_chat_ignores_a_socket_that_never_joined():
    async def scenario():
        room = GameRoom("r1")
        joined = _FakeWS()
        room.players = {joined: "Ada"}
        await room.handle_chat(_FakeWS(), "spam")
        return joined.sent

    assert asyncio.run(scenario()) == []


def test_broadcast_evicts_a_socket_that_fails_to_send():
    class _FailingWS:
        async def send_json(self, payload):
            raise RuntimeError("send failed")

    async def scenario():
        room = GameRoom("r1")
        good, bad = _FakeWS(), _FailingWS()
        room.players = {good: "Good", bad: "Bad"}
        await room.handle_chat(good, "hi")
        return good.sent, bad in room.players

    good_sent, bad_still_connected = asyncio.run(scenario())
    assert good_sent[0]["text"] == "hi"
    assert bad_still_connected is False


def test_chat_round_trips_over_the_socket(client):
    room_id = client.post("/api/rooms", json={"max_players": 2}).json()["room_id"]
    with client.websocket_connect(f"/ws/{room_id}") as ws:
        _join(ws, room_id, "Ada")
        ws.send_json({"type": "CHAT", "room": room_id, "chat": {"text": "hi all"}})
        assert ws.receive_json() == {
            "type": "CHAT",
            "room": room_id,
            "from": "Ada",
            "text": "hi all",
        }


def test_oversize_chat_closes_the_connection(client):
    room_id = client.post("/api/rooms", json={"max_players": 2}).json()["room_id"]
    with client.websocket_connect(f"/ws/{room_id}") as ws:
        _join(ws, room_id, "Ada")
        ws.send_json({"type": "CHAT", "room": room_id, "chat": {"text": "N" * 501}})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1003

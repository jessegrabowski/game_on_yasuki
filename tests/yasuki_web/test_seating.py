import asyncio

import pytest
from starlette.websockets import WebSocketDisconnect

from yasuki_web import websocket as ws_module
from yasuki_web.websocket import GameRoom
from yasuki_web.rooms import rooms
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.action_log import SessionEntry

from tests.yasuki_web._support import account, as_user


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


@pytest.fixture
def room():
    rooms["r1"] = {"players": [], "max_players": 2}
    try:
        yield GameRoom("r1")
    finally:
        rooms.pop("r1", None)


def test_seat_name_comes_from_the_account_not_the_join_frame(room):
    asyncio.run(room.add_player(_FakeWS(), {"id": 7, "display_name": "Hida Kisada"}))
    assert room.state.seats[PlayerId.P1].name == "Hida Kisada"


def test_second_tab_of_one_user_shares_the_single_seat(room):
    ada = account("Ada")
    first, second = _FakeWS(), _FakeWS()
    asyncio.run(room.add_player(first, ada))
    asyncio.run(room.add_player(second, ada))
    # Both connections drive seat P1; no second seat was consumed and the roster lists Ada once.
    assert room.seats[first] is PlayerId.P1
    assert room.seats[second] is PlayerId.P1
    assert room._free_seat() is PlayerId.P2
    assert rooms["r1"]["players"] == ["Ada"]


def test_a_second_tab_is_caught_up_privately_not_announced_as_a_join(room):
    ada = account("Ada")
    asyncio.run(room.add_player(_FakeWS(), ada))
    second = _FakeWS()
    asyncio.run(room.add_player(second, ada))
    joins = [
        e for e in room.action_log.entries if isinstance(e, SessionEntry) and e.event == "join"
    ]
    assert len(joins) == 1  # only the first connection announced a join
    assert second.sent[-1]["type"] == "SNAPSHOT"  # the new tab still gets the current view


def test_seat_survives_until_the_players_last_tab_leaves(room):
    ada = account("Ada")
    first, second = _FakeWS(), _FakeWS()
    asyncio.run(room.add_player(first, ada))
    asyncio.run(room.add_player(second, ada))

    asyncio.run(room.remove_player(first))
    # One tab closed, but the player still holds the seat: not marked disconnected, still rostered.
    assert room.seat_by_user[ada["id"]] is PlayerId.P1
    assert room.state.seats[PlayerId.P1].connected is True
    assert rooms["r1"]["players"] == ["Ada"]

    asyncio.run(room.remove_player(second))
    # Last tab gone: the seat frees, the player is unrostered, and the departure is recorded once.
    assert ada["id"] not in room.seat_by_user
    assert room.state.seats[PlayerId.P1].connected is False
    assert rooms["r1"]["players"] == []
    leaves = [
        e for e in room.action_log.entries if isinstance(e, SessionEntry) and e.event == "leave"
    ]
    assert len(leaves) == 1


def test_anonymous_handshake_is_closed(client, monkeypatch):
    room_id = client.post("/api/rooms", json={"max_players": 2}).json()["room_id"]

    async def no_user(websocket):
        return None

    monkeypatch.setattr(ws_module, "_authenticate", no_user)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/{room_id}"):
            pass
    assert exc.value.code == 4401
    assert exc.value.reason == "Authentication required"


def test_a_users_second_tab_leaves_the_opponent_seat_open(client):
    # The point of binding seats to user_id: one player on two tabs must not occupy both seats, so a
    # real opponent can still sit down.
    room_id = client.post("/api/rooms", json={"max_players": 2}).json()["room_id"]
    with (
        client.websocket_connect(f"/ws/{room_id}", headers=as_user("Ada")) as tab1,
        client.websocket_connect(f"/ws/{room_id}", headers=as_user("Ada")) as tab2,
    ):
        tab1.send_json({"type": "JOIN", "room": room_id, "join": {"name": "Ada"}})
        assert tab1.receive_json()["your_seat"] == "P1"

        tab2.send_json({"type": "JOIN", "room": room_id, "join": {"name": "Ada"}})
        assert tab2.receive_json()["your_seat"] == "P1"  # the same seat, not P2

        with client.websocket_connect(f"/ws/{room_id}", headers=as_user("Kenji")) as kenji:
            kenji.send_json({"type": "JOIN", "room": room_id, "join": {"name": "Kenji"}})
            assert kenji.receive_json()["your_seat"] == "P2"  # P2 was free for the opponent

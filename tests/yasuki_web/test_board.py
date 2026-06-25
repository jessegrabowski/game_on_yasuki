import asyncio

from yasuki_web.websocket import GameRoom


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


def _room_with_player():
    room = GameRoom("r1")
    ws = _FakeWS()
    room.players = {ws: "Ada"}
    return room, ws


def _card(card_id, **overrides):
    return {
        "id": card_id,
        "name": None,
        "img": None,
        "x": 0,
        "y": 0,
        "bowed": False,
        "face_up": True,
        **overrides,
    }


def test_add_card_appends_and_broadcasts():
    room, ws = _room_with_player()
    asyncio.run(
        room.handle_board_action(
            ws, {"kind": "ADD_CARD", "id": "c1", "name": "X", "img": "a.jpg", "x": 10, "y": 20}
        )
    )
    cards = room.game_state["cards"]
    assert len(cards) == 1
    assert cards[0] == _card("c1", name="X", img="a.jpg", x=10, y=20)
    assert ws.sent[-1]["state"]["cards"][0]["id"] == "c1"


def test_set_card_pos_moves_the_card():
    room, ws = _room_with_player()
    room.game_state["cards"] = [_card("c1")]
    asyncio.run(
        room.handle_board_action(ws, {"kind": "SET_CARD_POS", "id": "c1", "x": 50, "y": 60})
    )
    assert (room.game_state["cards"][0]["x"], room.game_state["cards"][0]["y"]) == (50, 60)


def test_card_flag_toggles_bowed_and_face_up():
    room, ws = _room_with_player()
    room.game_state["cards"] = [_card("c1")]
    asyncio.run(room.handle_board_action(ws, {"kind": "CARD_FLAG", "id": "c1", "flag": "bowed"}))
    assert room.game_state["cards"][0]["bowed"] is True
    asyncio.run(room.handle_board_action(ws, {"kind": "CARD_FLAG", "id": "c1", "flag": "face_up"}))
    assert room.game_state["cards"][0]["face_up"] is False


def test_remove_card_drops_only_that_card():
    room, ws = _room_with_player()
    room.game_state["cards"] = [_card("c1"), _card("c2")]
    asyncio.run(room.handle_board_action(ws, {"kind": "REMOVE_CARD", "id": "c1"}))
    assert [c["id"] for c in room.game_state["cards"]] == ["c2"]


def test_board_action_ignores_a_socket_that_never_joined():
    room = GameRoom("r1")
    room.players = {_FakeWS(): "Ada"}
    asyncio.run(room.handle_board_action(_FakeWS(), {"kind": "ADD_CARD", "id": "c1"}))
    assert room.game_state["cards"] == []


def test_board_action_round_trips_over_the_socket(client):
    room_id = client.post("/api/rooms", json={"max_players": 2}).json()["room_id"]
    with client.websocket_connect(f"/ws/{room_id}") as ws:
        ws.send_json({"type": "JOIN", "room": room_id, "join": {"name": "Ada"}})
        ws.receive_json()  # HELLO
        ws.receive_json()  # STATE
        ws.receive_json()  # LOG "Ada joined"
        ws.send_json(
            {
                "type": "BOARD",
                "room": room_id,
                "board": {
                    "kind": "ADD_CARD",
                    "id": "c1",
                    "name": "X",
                    "img": "a.jpg",
                    "x": 1,
                    "y": 2,
                },
            }
        )
        state = ws.receive_json()
        assert state["type"] == "STATE"
        assert state["state"]["cards"][0]["id"] == "c1"

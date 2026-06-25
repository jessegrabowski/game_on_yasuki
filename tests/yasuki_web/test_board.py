import asyncio

from yasuki_web.websocket import GameRoom
from yasuki_web.schemas import IntentEnvelope, SpawnRequest
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import IntentOp, BoardPos


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


def _room_with_seat():
    room = GameRoom("r1")
    ws = _FakeWS()
    room.seats = {ws: PlayerId.P1}
    room.players = {ws: "Ada"}
    room.state.seats[PlayerId.P1].name = "Ada"
    return room, ws


def _spawn(room, ws, **overrides):
    spawn = SpawnRequest(name="Hida", img="a.jpg", side="DYNASTY", x=10, y=20, **overrides)
    asyncio.run(room.handle_spawn(ws, spawn))
    return room.state.battlefield.cards[-1].id


def test_spawn_injects_a_public_card_logs_and_broadcasts():
    room, ws = _room_with_seat()
    _spawn(room, ws)

    card = room.state.battlefield.cards[0]
    assert card.owner is None and card.face_up is True
    assert room.action_log.entries[-1].intent.op is IntentOp.SPAWN_CARD  # a real logged intent
    snapshot = ws.sent[-1]
    assert snapshot["type"] == "SNAPSHOT"
    placed = snapshot["snapshot"]["battlefield"][0]
    assert placed["name"] == "Hida" and (placed["x"], placed["y"]) == (10, 20)


def test_spawn_assigns_a_distinct_server_id_each_time():
    room, ws = _room_with_seat()
    first = _spawn(room, ws)
    second = _spawn(room, ws)
    assert first != second
    assert {first, second} <= set(room.state.cards_by_id)


def test_remove_drops_the_card_and_logs():
    room, ws = _room_with_seat()
    card_id = _spawn(room, ws)
    asyncio.run(room.handle_remove(ws, card_id))
    assert room.state.battlefield.cards == []
    assert card_id not in room.state.cards_by_id
    assert room.action_log.entries[-1].intent.op is IntentOp.REMOVE_CARD


def test_spawn_ignored_from_an_unseated_socket():
    room = GameRoom("r1")
    room.seats = {_FakeWS(): PlayerId.P1}
    asyncio.run(room.handle_spawn(_FakeWS(), SpawnRequest(name="X", side="FATE")))
    assert room.state.battlefield.cards == []


def test_move_intent_repositions_and_logs():
    room, ws = _room_with_seat()
    card_id = _spawn(room, ws)

    env = IntentEnvelope(op=IntentOp.SET_CARD_POS, card_id=card_id, x=40.0, y=50.0)
    asyncio.run(room.handle_intent(ws, env))

    assert room.state.positions[card_id] == BoardPos(40.0, 50.0)
    assert room.action_log.entries[-1].intent.op is IntentOp.SET_CARD_POS
    assert ws.sent[-1]["type"] == "SNAPSHOT"


def test_flip_intent_toggles_face_up():
    room, ws = _room_with_seat()
    card_id = _spawn(room, ws)  # spawns face_up

    asyncio.run(room.handle_intent(ws, IntentEnvelope(op=IntentOp.FLIP, card_ids=[card_id])))

    assert room.state.cards_by_id[card_id].face_up is False


def test_rejected_intent_sends_error_and_is_not_logged():
    room, ws = _room_with_seat()
    before = len(room.action_log.entries)

    asyncio.run(room.handle_intent(ws, IntentEnvelope(op=IntentOp.FLIP, card_ids=["ghost"])))

    assert ws.sent[-1]["type"] == "ERROR"
    assert len(room.action_log.entries) == before


def test_malformed_intent_sends_error():
    room, ws = _room_with_seat()
    # MOVE_CARD with no destination → decode fails → clean rejection, not a crash.
    asyncio.run(room.handle_intent(ws, IntentEnvelope(op=IntentOp.MOVE_CARD, card_id="c1")))
    assert ws.sent[-1]["type"] == "ERROR"


def test_intent_ignored_from_an_unseated_socket():
    room, _ = _room_with_seat()
    stranger = _FakeWS()
    asyncio.run(room.handle_intent(stranger, IntentEnvelope(op=IntentOp.CREATE_PROVINCE)))
    assert stranger.sent == []


def test_spawn_round_trips_over_the_socket(client):
    room_id = client.post("/api/rooms", json={"max_players": 2}).json()["room_id"]
    with client.websocket_connect(f"/ws/{room_id}") as ws:
        ws.send_json({"type": "JOIN", "room": room_id, "join": {"name": "Ada"}})
        ws.receive_json()  # HELLO
        ws.receive_json()  # SNAPSHOT
        ws.receive_json()  # LOG "Ada joined"
        ws.send_json(
            {
                "type": "SPAWN",
                "room": room_id,
                "spawn": {"name": "X", "img": "a.jpg", "side": "FATE", "x": 1, "y": 2},
            }
        )
        snapshot = ws.receive_json()
        assert snapshot["type"] == "SNAPSHOT"
        assert snapshot["snapshot"]["battlefield"][0]["name"] == "X"

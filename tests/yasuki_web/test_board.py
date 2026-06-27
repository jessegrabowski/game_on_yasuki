import asyncio

import pytest

from yasuki_web.websocket import GameRoom
from yasuki_web.rooms import rooms
from yasuki_web.schemas import IntentEnvelope
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import IntentOp, BoardPos
from yasuki_core.engine.action_log import SessionEntry


@pytest.fixture
def registered_room():
    rooms["r1"] = {"players": [], "max_players": 2}
    try:
        yield GameRoom("r1")
    finally:
        rooms.pop("r1", None)


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
    fields = {"name": "Hida", "img": "a.jpg", "side": "DYNASTY", "position": [10, 20], **overrides}
    asyncio.run(room.handle_intent(ws, IntentEnvelope(op=IntentOp.SPAWN_CARD, **fields)))
    return room.state.battlefield.cards[-1].id


def test_spawn_injects_a_public_card_logs_and_broadcasts():
    room, ws = _room_with_seat()
    _spawn(room, ws)

    card = room.state.battlefield.cards[0]
    assert card.owner is None and card.face_up is True
    assert room.action_log.entries[-1].intent.op is IntentOp.SPAWN_CARD  # a real logged intent
    snapshot = [m for m in ws.sent if m["type"] == "SNAPSHOT"][-1]
    placed = snapshot["snapshot"]["battlefield"][0]
    assert placed["name"] == "Hida" and (placed["x"], placed["y"]) == (10, 20)


def test_spawn_logs_a_linked_card():
    room, ws = _room_with_seat()
    _spawn(room, ws)
    log = [m for m in ws.sent if m["type"] == "LOG"][-1]
    assert log["parts"][-1] == {"card_id": room.state.battlefield.cards[0].id, "name": "Hida"}


def test_spawn_assigns_a_distinct_server_id_each_time():
    room, ws = _room_with_seat()
    first = _spawn(room, ws)
    second = _spawn(room, ws)
    assert first != second
    assert {first, second} <= set(room.state.cards_by_id)


def test_remove_drops_the_card_and_logs():
    room, ws = _room_with_seat()
    card_id = _spawn(room, ws)
    asyncio.run(room.handle_intent(ws, IntentEnvelope(op=IntentOp.REMOVE_CARD, card_id=card_id)))
    assert room.state.battlefield.cards == []
    assert card_id not in room.state.cards_by_id
    assert room.action_log.entries[-1].intent.op is IntentOp.REMOVE_CARD


def test_spawn_ignored_from_an_unseated_socket():
    room = GameRoom("r1")
    room.seats = {_FakeWS(): PlayerId.P1}
    env = IntentEnvelope(op=IntentOp.SPAWN_CARD, name="X", side="FATE", position=[0, 0])
    asyncio.run(room.handle_intent(_FakeWS(), env))
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

    assert any(m["type"] == "ERROR" for m in ws.sent)
    assert len(room.action_log.entries) == before


def test_rejected_intent_reverts_the_sender_with_a_snapshot():
    # The error tells the client the move failed; the trailing snapshot reverts any optimistic local
    # change (a hidden drag source, a card nudged to its drop point) to the authoritative view.
    room, ws = _room_with_seat()

    asyncio.run(room.handle_intent(ws, IntentEnvelope(op=IntentOp.FLIP, card_ids=["ghost"])))

    assert ws.sent[-1]["type"] == "SNAPSHOT"


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
                "type": "INTENT",
                "room": room_id,
                "intent": {
                    "op": "SPAWN_CARD",
                    "name": "X",
                    "img": "a.jpg",
                    "side": "FATE",
                    "position": [1, 2],
                },
            }
        )
        snapshot = ws.receive_json()
        assert snapshot["type"] == "SNAPSHOT"
        assert snapshot["snapshot"]["battlefield"][0]["name"] == "X"


def test_seat_metadata_changes_advance_the_view_version(registered_room):
    room = registered_room
    ada, kenji = _FakeWS(), _FakeWS()
    asyncio.run(room.add_player(ada, "Ada"))
    after_join_1 = room.state.seq
    asyncio.run(room.add_player(kenji, "Kenji"))
    after_join_2 = room.state.seq
    asyncio.run(room.remove_player(kenji))
    after_leave = room.state.seq
    # Each non-intent metadata broadcast carries a strictly newer seq than the last.
    assert 0 < after_join_1 < after_join_2 < after_leave


def test_join_and_leave_are_recorded_on_the_session_tape(registered_room):
    room = registered_room
    ada = _FakeWS()
    asyncio.run(room.add_player(ada, "Ada"))
    asyncio.run(room.remove_player(ada))
    sessions = [(e.name, e.event) for e in room.action_log.entries if isinstance(e, SessionEntry)]
    assert sessions == [("Ada", "join"), ("Ada", "leave")]


def test_reset_carries_the_view_version_forward(registered_room):
    room = registered_room
    ada = _FakeWS()
    asyncio.run(room.add_player(ada, "Ada"))
    before = room.state.seq
    asyncio.run(room.handle_reset(ada))  # a lone seated player's vote is unanimous
    assert room.state.seq > before


def test_ready_advances_version_and_records_a_session_event(registered_room):
    room = registered_room
    ada = _FakeWS()
    asyncio.run(room.add_player(ada, "Ada"))
    room.pending_decks[PlayerId.P1] = {}  # past the "load a deck first" gate; one seat won't deal
    before = room.state.seq
    asyncio.run(room.handle_ready(ada, True))
    assert room.state.seq > before
    assert any(isinstance(e, SessionEntry) and e.event == "ready" for e in room.action_log.entries)

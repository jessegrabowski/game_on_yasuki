import asyncio

import pytest

from yasuki_web.websocket import GameRoom, active_game_rooms
from yasuki_web.rooms import rooms
from yasuki_web.schemas import IntentEnvelope
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import BoardPos, ZoneKey, ZoneRole
from yasuki_core.engine.intents import IntentOp
from yasuki_core.engine.action_log import SessionEntry
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, Side
from yasuki_core.game_pieces.prints import FatePrint, PersonalityPrint

from tests.yasuki_web._support import account


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
    # Seed a creatable-token template so a token_id spawn resolves with no database call.
    room.state.creatable_tokens.setdefault("hida", PersonalityPrint(name="Hida", side=Side.DYNASTY))
    fields = {"token_id": "hida", "position": [10, 20], **overrides}
    asyncio.run(room.handle_intent(ws, IntentEnvelope(op=IntentOp.SPAWN_CARD, **fields)))
    return room.state.battlefield.cards[-1].id


def test_spawn_injects_a_public_card_logs_and_broadcasts():
    room, ws = _room_with_seat()
    _spawn(room, ws)

    card = room.state.battlefield.cards[0]
    assert card.owner is PlayerId.P1 and card.face_up is True
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
    env = IntentEnvelope(op=IntentOp.SPAWN_CARD, token_id="x", position=[0, 0])
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
        active_game_rooms[room_id].state.creatable_tokens["x"] = PersonalityPrint(
            name="X", side=Side.DYNASTY
        )
        ws.send_json(
            {
                "type": "INTENT",
                "room": room_id,
                "intent": {"op": "SPAWN_CARD", "token_id": "x", "position": [1, 2]},
            }
        )
        snapshot = ws.receive_json()
        assert snapshot["type"] == "SNAPSHOT"
        assert snapshot["snapshot"]["battlefield"][0]["name"] == "X"


def test_seat_metadata_changes_advance_the_view_version(registered_room):
    room = registered_room
    ada, kenji = _FakeWS(), _FakeWS()
    asyncio.run(room.add_player(ada, account("Ada")))
    after_join_1 = room.state.seq
    asyncio.run(room.add_player(kenji, account("Kenji")))
    after_join_2 = room.state.seq
    asyncio.run(room.remove_player(kenji))
    after_leave = room.state.seq
    # Each non-intent metadata broadcast carries a strictly newer seq than the last.
    assert 0 < after_join_1 < after_join_2 < after_leave


def test_join_and_leave_are_recorded_on_the_session_tape(registered_room):
    room = registered_room
    ada = _FakeWS()
    asyncio.run(room.add_player(ada, account("Ada")))
    asyncio.run(room.remove_player(ada))
    sessions = [(e.name, e.event) for e in room.action_log.entries if isinstance(e, SessionEntry)]
    assert sessions == [("Ada", "join"), ("Ada", "leave")]


def test_reset_carries_the_view_version_forward(registered_room):
    room = registered_room
    ada = _FakeWS()
    asyncio.run(room.add_player(ada, account("Ada")))
    before = room.state.seq
    asyncio.run(room.handle_reset(ada))  # a lone seated player's vote is unanimous
    assert room.state.seq > before


def test_ready_advances_version_and_records_a_session_event(registered_room):
    room = registered_room
    ada = _FakeWS()
    asyncio.run(room.add_player(ada, account("Ada")))
    room.pending_decks[PlayerId.P1] = {}  # past the "load a deck first" gate; one seat won't deal
    before = room.state.seq
    asyncio.run(room.handle_ready(ada, True))
    assert room.state.seq > before
    assert any(isinstance(e, SessionEntry) and e.event == "ready" for e in room.action_log.entries)


def _two_seat_room():
    room = GameRoom("r1")
    first, second = _FakeWS(), _FakeWS()
    room.seats = {first: PlayerId.P1, second: PlayerId.P2}
    room.players = {first: "Ada", second: "Kai"}
    room.state.seats[PlayerId.P1].name = "Ada"
    room.state.seats[PlayerId.P2].name = "Kai"
    # The proxy reaches a real table from the rulebook pull; seed the template directly so the
    # handler resolves it without a database.
    room.state.creatable_tokens[IMPERIAL_FAVOR_ID] = FatePrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    return room, first, second


def _favor_ids(room):
    return [
        card_id
        for card_id, card in room.state.cards_by_id.items()
        if card.printed_id == IMPERIAL_FAVOR_ID
    ]


def test_taking_the_favor_puts_one_proxy_face_up_in_the_actors_hand():
    room, ws, other = _two_seat_room()

    asyncio.run(room.handle_take_favor(ws))

    hand = room.state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards
    assert [card.printed_id for card in hand] == [IMPERIAL_FAVOR_ID]
    # A hand is private to its owner, so the opponent identifying the card is what shown buys.
    opponent = [m for m in other.sent if m["type"] == "SNAPSHOT"][-1]["snapshot"]
    seen = [c for zone in opponent["zones"].values() for c in zone if not c["hidden"]]
    assert [card["name"] for card in seen] == ["The Imperial Favor"]


def test_taking_the_favor_sweeps_every_seats_proxy():
    """Only one player holds the Favor at a time, so taking it clears the copy in the other seat's
    hand rather than leaving two on the table."""
    room, first, second = _two_seat_room()
    asyncio.run(room.handle_take_favor(second))
    assert len(_favor_ids(room)) == 1

    asyncio.run(room.handle_take_favor(first))

    assert len(_favor_ids(room)) == 1
    assert room.state.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)].cards == []
    assert len(room.state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards) == 1


def test_taking_the_favor_twice_from_one_seat_leaves_one_proxy():
    """Re-taking it is a no-op in effect: the sweep clears the actor's own copy before respawning."""
    room, ws, _ = _two_seat_room()

    asyncio.run(room.handle_take_favor(ws))
    asyncio.run(room.handle_take_favor(ws))

    assert len(_favor_ids(room)) == 1


def test_take_favor_ignored_from_an_unseated_socket():
    room, _, _ = _two_seat_room()

    asyncio.run(room.handle_take_favor(_FakeWS()))

    assert _favor_ids(room) == []


def test_the_favor_carries_its_locked_actions_on_the_wire():
    """The client leaves a locked item off the menu, and nothing else in the payload says which
    actions a card refuses."""
    room, ws, other = _two_seat_room()

    asyncio.run(room.handle_take_favor(ws))

    snapshot = [m for m in ws.sent if m["type"] == "SNAPSHOT"][-1]["snapshot"]
    cards = [card for zone in snapshot["zones"].values() for card in zone]
    assert [card["locked"] for card in cards] == [["UNSHOW"]]

    # The opponent sees it too, since it is shown, and needs the same list.
    opponent = [m for m in other.sent if m["type"] == "SNAPSHOT"][-1]["snapshot"]
    seen = [c for zone in opponent["zones"].values() for c in zone if not c["hidden"]]
    assert [card["locked"] for card in seen] == [["UNSHOW"]]


def _log_lines(ws):
    return [m["parts"][0]["text"] for m in ws.sent if m["type"] == "LOG"]


def test_the_log_names_who_lost_the_favor():
    room, first, second = _two_seat_room()
    asyncio.run(room.handle_take_favor(first))

    asyncio.run(room.handle_take_favor(second))

    assert _log_lines(first) == [
        "Ada takes the Imperial Favor",
        "Kai takes the Imperial Favor from Ada",
    ]


def test_retaking_your_own_favor_names_nobody():
    room, first, _ = _two_seat_room()
    asyncio.run(room.handle_take_favor(first))

    asyncio.run(room.handle_take_favor(first))

    assert _log_lines(first) == ["Ada takes the Imperial Favor"] * 2


def test_a_favor_that_cannot_be_spawned_is_not_swept_from_its_holder():
    """The sweep is destructive, so it must not run when the spawn that replaces it cannot. A table
    between a reset and its next deal has no template to spawn from."""
    room, first, second = _two_seat_room()
    asyncio.run(room.handle_take_favor(first))
    held = _favor_ids(room)[0]
    del room.state.creatable_tokens[IMPERIAL_FAVOR_ID]

    asyncio.run(room.handle_take_favor(second))

    assert _favor_ids(room)[0] == held
    assert room.state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards[0].id == held
    assert [m["message"] for m in second.sent if m["type"] == "ERROR"] == [
        "Could not take the Favor"
    ]

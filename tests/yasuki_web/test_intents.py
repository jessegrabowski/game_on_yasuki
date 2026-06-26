import asyncio

import pytest

from yasuki_web.websocket import GameRoom
from yasuki_web.schemas import IntentEnvelope
from yasuki_web.rooms import rooms
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import IntentOp, ZoneKey, ZoneRole
from yasuki_core.engine.action_log import ChatEntry
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


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


def _seat_two(room):
    ada, kenji = _FakeWS(), _FakeWS()
    asyncio.run(room.add_player(ada, "Ada"))
    asyncio.run(room.add_player(kenji, "Kenji"))
    return ada, kenji


def _hand_card(room, seat, card_id="f1", name="Secret"):
    card = L5RCard(id=card_id, name=name, side=Side.FATE, owner=seat, face_up=False)
    room.state.zones[ZoneKey(seat, ZoneRole.HAND)].cards.append(card)
    room.state.cards_by_id[card_id] = card
    return card


def test_first_two_players_get_distinct_seats(room):
    ada, kenji = _seat_two(room)
    assert room.seats == {ada: PlayerId.P1, kenji: PlayerId.P2}
    assert ada.sent[0]["your_seat"] == "P1"
    assert kenji.sent[0]["your_seat"] == "P2"


def test_third_player_is_rejected_as_table_full(room):
    _seat_two(room)
    third = _FakeWS()
    asyncio.run(room.add_player(third, "Shiro"))
    assert third not in room.seats
    assert third.sent[-1]["type"] == "ERROR"


def test_leaving_frees_the_seat_for_a_new_player(room):
    ada, _ = _seat_two(room)
    asyncio.run(room.remove_player(ada))
    shiro = _FakeWS()
    asyncio.run(room.add_player(shiro, "Shiro"))
    assert room.seats[shiro] is PlayerId.P1  # P1 reopened


def test_each_seat_receives_its_own_redacted_snapshot(room):
    ada, kenji = _seat_two(room)
    _hand_card(room, PlayerId.P1)  # Ada's face-down hand card

    asyncio.run(room.broadcast_snapshots())

    ada_hand = ada.sent[-1]["snapshot"]["zones"]["P1:hand"][0]
    kenji_hand = kenji.sent[-1]["snapshot"]["zones"]["P1:hand"][0]
    assert ada_hand["name"] == "Secret"  # owner sees their own card
    # The opponent gets a stub: the public owner, but no identity.
    assert kenji_hand == {"id": "f1", "side": "FATE", "owner": "P1", "hidden": True}


def test_accepted_intent_mutates_logs_and_broadcasts_to_both(room):
    ada, kenji = _seat_two(room)
    before = len(room.action_log.entries)

    asyncio.run(room.handle_intent(ada, IntentEnvelope(op=IntentOp.SET_HONOR, value=20)))

    assert room.state.seats[PlayerId.P1].honor == 20
    assert len(room.action_log.entries) == before + 1
    assert kenji.sent[-1]["type"] == "LOG"
    assert kenji.sent[-1]["parts"] == [{"text": "Ada "}, {"text": "set their honor to 20"}]
    assert any(m["type"] == "SNAPSHOT" for m in kenji.sent)


def test_opponent_targeting_intent_is_rejected_and_unlogged(room):
    ada, kenji = _seat_two(room)
    _hand_card(room, PlayerId.P2, name="Theirs")  # belongs to Kenji
    before = len(room.action_log.entries)
    kenji.sent.clear()

    asyncio.run(room.handle_intent(ada, IntentEnvelope(op=IntentOp.FLIP, card_ids=["f1"])))

    assert ada.sent[-1]["type"] == "ERROR"
    assert len(room.action_log.entries) == before  # nothing recorded
    assert kenji.sent == []  # a rejected intent broadcasts nothing


def test_chat_is_recorded_on_the_durable_tape(room):
    ada, _ = _seat_two(room)
    asyncio.run(room.handle_chat(ada, "hello"))

    chats = [e for e in room.action_log.entries if isinstance(e, ChatEntry)]
    assert len(chats) == 1
    assert (chats[0].sender, chats[0].text) == ("Ada", "hello")


def test_chat_and_intents_share_one_ordered_tape(room):
    ada, _ = _seat_two(room)
    asyncio.run(room.handle_intent(ada, IntentEnvelope(op=IntentOp.CREATE_PROVINCE)))
    asyncio.run(room.handle_chat(ada, "made a province"))
    asyncio.run(room.handle_intent(ada, IntentEnvelope(op=IntentOp.SET_HONOR, value=5)))

    # The chat lands between the two intents on a single tape.
    is_chat = [isinstance(entry, ChatEntry) for entry in room.action_log.entries]
    assert is_chat == [False, True, False]

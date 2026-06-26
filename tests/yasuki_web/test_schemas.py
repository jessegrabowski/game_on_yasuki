import pytest
from pydantic import ValidationError

from yasuki_web.schemas import (
    ChatRequest,
    ClientMessage,
    IntentEnvelope,
    intent_from_envelope,
    ServerChat,
    ServerDeckContents,
    ServerLog,
    ServerSnapshot,
)
from yasuki_core.engine.table import IntentOp, MoveCard, BATTLEFIELD, BoardPos


def test_chat_client_message_parses():
    msg = ClientMessage.model_validate({"type": "CHAT", "room": "r1", "chat": {"text": "hi"}})
    assert msg.type == "CHAT"
    assert msg.chat.text == "hi"


@pytest.mark.parametrize("length,valid", [(0, False), (1, True), (500, True), (501, False)])
def test_chat_text_length_bounds(length, valid):
    if valid:
        assert ChatRequest(text="N" * length).text == "N" * length
    else:
        with pytest.raises(ValidationError):
            ChatRequest(text="N" * length)


def test_server_chat_serializes_sender_as_from():
    payload = ServerChat(room="r1", sender="Ada", text="hi").model_dump(by_alias=True)
    assert payload == {"type": "CHAT", "room": "r1", "from": "Ada", "text": "hi"}


def test_server_log_serializes():
    assert ServerLog(room="r1", parts=[{"text": "Ada joined"}]).model_dump() == {
        "type": "LOG",
        "room": "r1",
        "parts": [{"text": "Ada joined"}],
    }


def test_intent_message_parses():
    msg = ClientMessage.model_validate(
        {"type": "INTENT", "room": "r1", "intent": {"op": "FLIP", "card_ids": ["c1"]}}
    )
    assert msg.type == "INTENT"
    assert msg.intent.op is IntentOp.FLIP


def test_intent_rejects_unknown_op():
    with pytest.raises(ValidationError):
        ClientMessage.model_validate({"type": "INTENT", "room": "r1", "intent": {"op": "HACK"}})


def test_intent_from_envelope_builds_a_core_intent():
    env = IntentEnvelope(
        op=IntentOp.MOVE_CARD, card_id="c1", to={"kind": "battlefield"}, position=[3.0, 4.0]
    )
    assert intent_from_envelope(env) == MoveCard("c1", BATTLEFIELD, BoardPos(3.0, 4.0))


def test_spawn_message_parses():
    msg = ClientMessage.model_validate(
        {
            "type": "SPAWN",
            "room": "r1",
            "spawn": {"name": "X", "img": "a.jpg", "side": "DYNASTY", "x": 1, "y": 2},
        }
    )
    assert msg.spawn.name == "X" and msg.spawn.side == "DYNASTY"


def test_server_snapshot_wraps_the_view():
    payload = ServerSnapshot(room="r1", snapshot={"seq": 3}).model_dump()
    assert payload == {"type": "SNAPSHOT", "room": "r1", "snapshot": {"seq": 3}}


def test_server_deck_contents_serializes_top_first():
    payload = ServerDeckContents(
        room="r1",
        deck={"owner": "P1", "side": "FATE"},
        cards=[{"id": "t3", "name": "Card t3"}, {"id": "b1", "name": "Card b1"}],
    ).model_dump()
    assert payload == {
        "type": "DECK_CONTENTS",
        "room": "r1",
        "deck": {"owner": "P1", "side": "FATE"},
        "cards": [{"id": "t3", "name": "Card t3"}, {"id": "b1", "name": "Card b1"}],
    }

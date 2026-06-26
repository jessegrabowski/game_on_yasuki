import pytest
from pydantic import ValidationError

from yasuki_web.schemas import (
    ChatRequest,
    ClientMessage,
    IntentEnvelope,
    intent_from_envelope,
    ServerChat,
    ServerDeckContents,
    ServerError,
    ServerLog,
    ServerSnapshot,
)
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    IntentOp,
    MoveCard,
    MoveDeckTop,
    Raise,
    SearchDeck,
    DeckKey,
    ZoneKey,
    ZoneRole,
    BATTLEFIELD,
    BoardPos,
)
from yasuki_core.game_pieces.constants import Side


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


def test_server_error_defaults_to_user_facing():
    assert ServerError(room="r1", message="Table is full").model_dump() == {
        "type": "ERROR",
        "room": "r1",
        "message": "Table is full",
        "debug": False,
    }


def test_server_error_carries_a_debug_flag():
    payload = ServerError(room="r1", message="Intent rejected", debug=True).model_dump()
    assert payload["debug"] is True


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


def test_move_deck_top_envelope_builds_a_core_intent():
    env = IntentEnvelope(
        op=IntentOp.MOVE_DECK_TOP,
        deck={"owner": "P1", "side": "FATE"},
        to={"kind": "battlefield"},
        position=[1.0, 2.0],
    )
    assert intent_from_envelope(env) == MoveDeckTop(
        DeckKey(PlayerId.P1, Side.FATE), BATTLEFIELD, BoardPos(1.0, 2.0)
    )


def test_move_deck_top_to_a_zone_destination():
    env = IntentEnvelope(
        op=IntentOp.MOVE_DECK_TOP,
        deck={"owner": "P2", "side": "DYNASTY"},
        to={"kind": "zone", "zone": {"owner": "P2", "role": "province", "idx": 0}},
    )
    assert intent_from_envelope(env) == MoveDeckTop(
        DeckKey(PlayerId.P2, Side.DYNASTY), ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 0), None
    )


def test_raise_envelope_builds_a_core_intent():
    env = IntentEnvelope(op=IntentOp.RAISE, card_id="c1")
    assert intent_from_envelope(env) == Raise("c1")


def test_search_deck_value_decodes_to_limit():
    env = IntentEnvelope(op=IntentOp.SEARCH_DECK, deck={"owner": "P1", "side": "DYNASTY"}, value=4)
    assert intent_from_envelope(env) == SearchDeck(DeckKey(PlayerId.P1, Side.DYNASTY), limit=4)


def test_search_deck_without_value_searches_the_whole_deck():
    env = IntentEnvelope(op=IntentOp.SEARCH_DECK, deck={"owner": "P1", "side": "FATE"})
    assert intent_from_envelope(env) == SearchDeck(DeckKey(PlayerId.P1, Side.FATE), limit=None)


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

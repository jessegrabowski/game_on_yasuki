import pytest
from pydantic import ValidationError

from yasuki_web.schemas import ChatRequest, ClientMessage, ServerChat


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


def test_board_action_parses():
    msg = ClientMessage.model_validate(
        {
            "type": "BOARD",
            "room": "r1",
            "board": {
                "kind": "ADD_CARD",
                "id": "c1",
                "name": "X",
                "img": "a.jpg",
                "x": 10,
                "y": 20,
            },
        }
    )
    assert msg.board.kind == "ADD_CARD"
    assert msg.board.id == "c1"


def test_board_action_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        ClientMessage.model_validate(
            {"type": "BOARD", "room": "r1", "board": {"kind": "HACK", "id": "c1"}}
        )

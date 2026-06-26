import asyncio

import pytest
from pydantic import ValidationError

from yasuki_web.websocket import GameRoom
from yasuki_web.schemas import ClientMessage, LoadDeckRequest
from yasuki_web.rooms import rooms
from yasuki_core.engine.players import PlayerId

DECK_YAML = """\
name: Crab Beats

Pre-Game:
  - Kyuden Hida [Imperial Edition]

Dynasty:
  - 2x Kuni Yori [Pearl Edition]

Fate:
  - 2x Ambush [Lotus Edition]
"""


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


def _seat(room, name="Ada"):
    ws = _FakeWS()
    asyncio.run(room.add_player(ws, name))
    return ws


def test_load_deck_is_accepted_as_a_client_message_type():
    msg = ClientMessage(type="LOAD_DECK", room="r1", load_deck=LoadDeckRequest(yaml=DECK_YAML))
    assert msg.load_deck.yaml == DECK_YAML


def test_empty_deck_yaml_is_rejected_by_the_schema():
    with pytest.raises(ValidationError):
        LoadDeckRequest(yaml="")


def test_loading_a_deck_stashes_parsed_lists_for_the_seat(room):
    ws = _seat(room)
    asyncio.run(room.handle_load_deck(ws, DECK_YAML))

    stashed = room.pending_decks[PlayerId.P1]
    assert [e["name"] for e in stashed["pre_game"]] == ["Kyuden Hida"]
    assert stashed["dynasty"][0] == {
        "name": "Kuni Yori",
        "count": 2,
        "set_name": "Pearl Edition",
        "art": None,
    }
    assert [e["name"] for e in stashed["fate"]] == ["Ambush"]


def test_a_deck_with_no_recognizable_cards_is_rejected_and_not_stashed(room):
    ws = _seat(room)
    asyncio.run(room.handle_load_deck(ws, "not a decklist at all"))

    assert PlayerId.P1 not in room.pending_decks
    assert ws.sent[-1]["type"] == "ERROR"


def test_load_deck_from_an_unseated_socket_is_a_noop(room):
    ws = _FakeWS()  # never joined, so it holds no seat
    asyncio.run(room.handle_load_deck(ws, DECK_YAML))
    assert room.pending_decks == {}


def test_loading_a_deck_announces_it_with_its_name(room):
    ws = _seat(room)
    asyncio.run(room.handle_load_deck(ws, DECK_YAML))

    log = ws.sent[-1]
    assert log["type"] == "LOG"
    assert log["parts"] == [{"text": "Ada loaded "}, {"text": "Crab Beats"}]


def test_a_nameless_deck_announces_the_client_filename(room):
    ws = _seat(room)
    asyncio.run(room.handle_load_deck(ws, "Fate:\n  - Ambush\n", filename="crab-beats.yaml"))

    assert ws.sent[-1]["parts"] == [{"text": "Ada loaded "}, {"text": "crab-beats.yaml"}]


def test_a_nameless_deck_with_no_filename_falls_back_to_a_generic_label(room):
    ws = _seat(room)
    asyncio.run(room.handle_load_deck(ws, "Fate:\n  - Ambush\n"))

    assert ws.sent[-1]["parts"] == [{"text": "Ada loaded "}, {"text": "a deck"}]


def test_a_rejected_deck_is_not_announced(room):
    ws = _seat(room)
    asyncio.run(room.handle_load_deck(ws, "not a decklist at all"))

    assert all(m["type"] != "LOG" or "loaded" not in m["parts"][0].get("text", "") for m in ws.sent)


def test_each_seat_stashes_its_own_deck(room):
    ada = _seat(room, "Ada")
    kenji = _seat(room, "Kenji")
    asyncio.run(room.handle_load_deck(ada, DECK_YAML))
    asyncio.run(room.handle_load_deck(kenji, "name: Crane\nDynasty:\n  - Doji Hoturi"))

    assert room.pending_decks[PlayerId.P1]["name"] == "Crab Beats"
    assert room.pending_decks[PlayerId.P2]["name"] == "Crane"
